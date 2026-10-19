import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from app.cache import Cache, CacheError
from app.cities import CITIES, City
from app.clients.open_meteo import OpenMeteoClient
from app.errors import UpstreamError
from app.schemas import CloudCover, CurrentWeather, WeatherResponse
from app.services.forecast import (
    INVALID_RESPONSE_ERRORS,
    FiniteFloat,
    build_daily,
    build_hourly,
    from_unix,
)
from app.services.weather_codes import classify_weather_code

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]


class _RawCurrent(BaseModel):
    """Open-Meteo の current のうち、使う項目。欠けている・null・型違いは検証で落とす。"""

    # 数値の文字列や真偽値を数値として受け付けない。
    model_config = ConfigDict(strict=True)

    # UNIX 秒（timeformat=unixtime）。
    time: int
    temperature_2m: float
    apparent_temperature: float
    dew_point_2m: float
    relative_humidity_2m: int
    precipitation: float
    weather_code: int
    cloud_cover: int
    cloud_cover_low: int
    cloud_cover_mid: int
    cloud_cover_high: int
    wind_speed_10m: float
    wind_direction_10m: FiniteFloat


class _CacheEntry(BaseModel):
    """キャッシュに保存する形。整形前の応答と、外部APIから取得した時刻。"""

    # 数値やタイムゾーンのない時刻を取得時刻として受け付けない。
    model_config = ConfigDict(strict=True)

    fetched_at: AwareDatetime
    raw: dict[str, Any]


@dataclass(frozen=True)
class Source:
    """整形に渡す応答が、どこから来たか。"""

    # 外部APIから取得した時刻。
    fetched_at: datetime
    # 行を選ぶ基準の時刻。いま取得した応答では取得時刻と同じ。
    now: datetime
    cached: bool = False
    stale: bool = False


# 整形前の応答を、エンドポイントの応答にする関数（`/weather` と `/cloud-base` で違う）。
# その応答が使えなければ UpstreamError。
type Builder[T] = Callable[[Mapping[str, Any], Source], T]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_current(raw: Mapping[str, Any]) -> tuple[_RawCurrent, datetime]:
    try:
        current = _RawCurrent.model_validate(raw.get("current"))
        return current, from_unix(current.time)
    except INVALID_RESPONSE_ERRORS as exc:
        logger.warning("open-meteo response is missing required current fields")
        raise UpstreamError("invalid current") from exc


def build_weather_response(
    city: City,
    raw: Mapping[str, Any],
    fetched_at: datetime,
    *,
    now: datetime | None = None,
    cached: bool = False,
    stale: bool = False,
) -> WeatherResponse:
    """`now` は hourly の 24 件を選ぶ基準。省略時は取得時刻（いま取得した応答）。"""
    current, time = _parse_current(raw)
    return WeatherResponse(
        city=city.value,
        timezone=CITIES[city].timezone,
        current=CurrentWeather(
            time=time,
            weather_code=current.weather_code,
            weather=classify_weather_code(current.weather_code),
            temperature_c=current.temperature_2m,
            apparent_temperature_c=current.apparent_temperature,
            dew_point_c=current.dew_point_2m,
            relative_humidity=current.relative_humidity_2m,
            precipitation_mm=current.precipitation,
            wind_speed_ms=current.wind_speed_10m,
            wind_direction_deg=current.wind_direction_10m,
            cloud_cover=CloudCover(
                total=current.cloud_cover,
                low=current.cloud_cover_low,
                mid=current.cloud_cover_mid,
                high=current.cloud_cover_high,
            ),
        ),
        hourly=build_hourly(raw, fetched_at if now is None else now),
        daily=build_daily(raw),
        source="open-meteo",
        fetched_at=fetched_at.astimezone(UTC).replace(microsecond=0),
        cached=cached,
        stale=stale,
    )


def cache_key(city: City) -> str:
    # 利用者が送った文字列ではなく、許可リスト（Enum）の値から作る。
    return f"weather:{city.value}"


async def _load_entry(cache: Cache, key: str) -> _CacheEntry | None:
    try:
        stored = await cache.get(key)
    except CacheError:
        # キャッシュの故障で API を止めない。例外の文面（接続先を含みうる）は出さない。
        logger.warning("cache read failed; fetching from open-meteo")
        return None
    if stored is None:
        return None
    try:
        return _CacheEntry.model_validate_json(stored)
    except ValidationError:
        logger.warning("cache entry is not in the expected format; ignoring it")
        return None


def _is_fresh(entry: _CacheEntry, now: datetime, ttl_s: int) -> bool:
    # 取得時刻が未来（時計が戻ったなど）の保存値は使わない。TTL ちょうどは期限切れ。
    return timedelta(0) <= now - entry.fetched_at < timedelta(seconds=ttl_s)


def _is_usable_as_stale(entry: _CacheEntry, now: datetime, stale_max_age_s: int) -> bool:
    # 上限ちょうどは使う（「最大 6 時間前まで」）。取得時刻が未来の保存値は使わない。
    return timedelta(0) <= now - entry.fetched_at <= timedelta(seconds=stale_max_age_s)


def _from_entry[T](
    entry: _CacheEntry, now: datetime, build: Builder[T], *, stale: bool
) -> T | None:
    try:
        # 保存してあるのは整形前の応答。hourly はいまの時刻で選び直す。
        source = Source(fetched_at=entry.fetched_at, now=now, cached=True, stale=stale)
        return build(entry.raw, source)
    except UpstreamError:
        logger.warning("cached forecast is no longer usable")
        return None


def _fresh_response[T](
    entry: _CacheEntry | None, now: datetime, ttl_s: int, build: Builder[T]
) -> T | None:
    if entry is None or not _is_fresh(entry, now, ttl_s):
        return None
    return _from_entry(entry, now, build, stale=False)


def _stale_response[T](
    city: City, entry: _CacheEntry | None, now: datetime, stale_max_age_s: int, build: Builder[T]
) -> T | None:
    if entry is None or not _is_usable_as_stale(entry, now, stale_max_age_s):
        return None
    response = _from_entry(entry, now, build, stale=True)
    if response is not None:
        age_s = int((now - entry.fetched_at).total_seconds())
        logger.warning("open-meteo failed; returning stale cache (%s, %d s old)", city.value, age_s)
    return response


async def _store(
    cache: Cache, city: City, raw: dict[str, Any], fetched_at: datetime, expire_s: int
) -> None:
    entry = _CacheEntry(fetched_at=fetched_at.astimezone(UTC), raw=raw)
    try:
        await cache.set(cache_key(city), entry.model_dump_json(), expire_s)
    except CacheError:
        logger.warning("cache write failed; returning the response without caching")


async def get_forecast[T](
    city: City,
    client: OpenMeteoClient,
    clock: Clock,
    cache: Cache,
    ttl_s: int,
    stale_max_age_s: int,
    build: Builder[T],
) -> T:
    """新しい保存値があれば使い、なければ外部APIを呼ぶ。失敗したら古い保存値で代える。"""
    entry = await _load_entry(cache, cache_key(city))
    fresh = _fresh_response(entry, clock(), ttl_s, build)
    if fresh is not None:
        return fresh
    try:
        raw = await client.fetch_forecast(city)
        fetched_at = clock()
        # 整形に成功した応答だけを保存する（壊れた応答を保存すると 502 が続く）。
        response = build(raw, Source(fetched_at=fetched_at, now=fetched_at))
    except UpstreamError:
        # 外部APIの失敗・壊れた応答のときは、上限までの古い保存値で代える。なければ 502。
        stale = _stale_response(city, entry, clock(), stale_max_age_s, build)
        if stale is None:
            raise
        return stale
    # 新しいかどうかは取得時刻で判定する。保存先の期限は、stale の上限まで残すためのもの。
    await _store(cache, city, raw, fetched_at, stale_max_age_s)
    return response


async def get_weather(
    city: City,
    client: OpenMeteoClient,
    clock: Clock,
    cache: Cache,
    ttl_s: int,
    stale_max_age_s: int,
) -> WeatherResponse:
    def build(raw: Mapping[str, Any], source: Source) -> WeatherResponse:
        return build_weather_response(
            city, raw, source.fetched_at, now=source.now, cached=source.cached, stale=source.stale
        )

    return await get_forecast(city, client, clock, cache, ttl_s, stale_max_age_s, build)
