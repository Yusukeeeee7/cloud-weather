import asyncio
import copy
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.cache import Cache, CacheError, MemoryCache
from app.cities import City
from app.clients.open_meteo import OpenMeteoClient, build_http_client
from app.config import Settings
from app.errors import UpstreamError
from app.schemas import WeatherResponse
from app.services.weather import get_weather
from tests.conftest import FIXED_NOW, FORECAST_URL, FakeClock, RawForecast

# spec.md「6. キャッシュ」：TTL 15 分、stale は最大 6 時間前まで。
TTL_S = 900
STALE_MAX_AGE_S = 6 * 60 * 60
TOKYO_KEY = "weather:tokyo"
# 最初の 1 回 + リトライ 2 回。
MAX_ATTEMPTS = 3
FETCHED_AT = FIXED_NOW.replace(microsecond=0)


class _RecordingCache:
    """保存のときに渡された期限を記録するキャッシュ。読み出しは常に「ない」。"""

    def __init__(self) -> None:
        self.expiries: list[int] = []

    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, expire_s: int) -> None:
        self.expiries.append(expire_s)

    async def close(self) -> None:
        return None


class _FailingReadCache:
    """読み出しが必ず失敗するキャッシュ。"""

    async def get(self, key: str) -> str | None:
        raise CacheError("redis://dummy-host:6379 is unreachable")

    async def set(self, key: str, value: str, expire_s: int) -> None:
        return None

    async def close(self) -> None:
        return None


class _SteppingClock:
    """呼ぶたびに、渡した時刻を順に返す時計（リトライの間に時間が進む場合を作る）。"""

    def __init__(self, times: list[datetime]) -> None:
        self._times = iter(times)

    def __call__(self) -> datetime:
        return next(self._times)


def _call(
    city: City,
    clock: FakeClock | _SteppingClock,
    cache: Cache,
    ttl_s: int = TTL_S,
    stale_max_age_s: int = STALE_MAX_AGE_S,
) -> WeatherResponse:
    async def run() -> WeatherResponse:
        settings = Settings(_env_file=None)
        async with build_http_client(settings) as http:
            client = OpenMeteoClient(http, settings)
            return await get_weather(city, client, clock, cache, ttl_s, stale_max_age_s)

    return asyncio.run(run())


def _read(cache: Cache, key: str) -> str | None:
    return asyncio.run(cache.get(key))


def _write(cache: Cache, key: str, value: str) -> None:
    asyncio.run(cache.set(key, value, STALE_MAX_AGE_S))


def _ok(raw: RawForecast) -> httpx.Response:
    return httpx.Response(200, json=raw)


def _seed(
    open_meteo: respx.MockRouter, raw: RawForecast, cache: Cache, clock: FakeClock
) -> tuple[respx.Route, WeatherResponse]:
    """外部APIが正常なうちに 1 回取得して保存する。その後、外部APIを 500 にする。"""
    route = open_meteo.get(FORECAST_URL).mock(return_value=_ok(raw))
    first = _call(City.TOKYO, clock, cache)
    assert route.call_count == 1
    route.mock(return_value=httpx.Response(500))
    return route, first


def test_service_upstream_failure_returns_stale(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # 受け入れ条件：stale 返却。
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    route, first = _seed(open_meteo, forecast("tokyo"), cache, clock)

    clock.now = FIXED_NOW + timedelta(minutes=20)
    response = _call(City.TOKYO, clock, cache)

    # リトライを使い切ってから、保存値を返す。
    assert route.call_count == 1 + MAX_ATTEMPTS
    assert response.stale is True
    # 値の出どころはキャッシュ（2026-10-12 決定）。
    assert response.cached is True
    # 取得した時刻は、最初に外部APIから取得した時刻のまま。
    assert response.fetched_at == FETCHED_AT
    assert response.current == first.current
    assert response.daily == first.daily
    assert len(response.hourly) == 24


@pytest.mark.parametrize(
    ("elapsed_s", "returns_stale"),
    [(STALE_MAX_AGE_S - 1, True), (STALE_MAX_AGE_S, True), (STALE_MAX_AGE_S + 1, False)],
)
def test_service_stale_max_age_boundary(
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    elapsed_s: int,
    returns_stale: bool,
) -> None:
    # ちょうど 6 時間は返す。6 時間を過ぎたら 502（2026-10-12 決定）。
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    _seed(open_meteo, forecast("tokyo"), cache, clock)

    clock.now = FIXED_NOW + timedelta(seconds=elapsed_s)
    if returns_stale:
        response = _call(City.TOKYO, clock, cache)
        assert response.stale is True
        assert response.fetched_at == FETCHED_AT
    else:
        with pytest.raises(UpstreamError):
            _call(City.TOKYO, clock, cache)


def test_service_stale_age_is_measured_after_the_failure(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # リトライの間に上限をまたいだら返さない。経過時間は、失敗が分かった時点の時刻で測る。
    cache = MemoryCache()
    _seed(open_meteo, forecast("tokyo"), cache, FakeClock(FIXED_NOW))
    before_fetch = FIXED_NOW + timedelta(seconds=STALE_MAX_AGE_S - 1)
    after_failure = FIXED_NOW + timedelta(seconds=STALE_MAX_AGE_S + 1)

    with pytest.raises(UpstreamError):
        _call(City.TOKYO, _SteppingClock([before_fetch, after_failure]), cache)


@pytest.mark.parametrize(
    "upstream",
    [{"side_effect": httpx.ReadTimeout}, {"return_value": httpx.Response(500)}],
)
def test_service_failure_without_cache_raises(
    open_meteo: respx.MockRouter, upstream: dict[str, object]
) -> None:
    # 受け入れ条件：使えるキャッシュがなければ 502（UpstreamError）。
    route = open_meteo.get(FORECAST_URL).mock(**upstream)

    with pytest.raises(UpstreamError):
        _call(City.TOKYO, FakeClock(FIXED_NOW), MemoryCache())

    assert route.call_count == MAX_ATTEMPTS


def test_service_fresh_hit_is_not_stale(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(return_value=_ok(forecast("tokyo")))
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    _call(City.TOKYO, clock, cache)

    clock.now = FIXED_NOW + timedelta(minutes=5)
    hit = _call(City.TOKYO, clock, cache)

    assert route.call_count == 1
    assert (hit.cached, hit.stale) == (True, False)


def test_service_fresh_fetch_is_not_stale(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    open_meteo.get(FORECAST_URL).mock(return_value=_ok(forecast("tokyo")))

    response = _call(City.TOKYO, FakeClock(FIXED_NOW), MemoryCache())

    assert (response.cached, response.stale) == (False, False)


def test_service_fresh_hit_does_not_call_failing_upstream(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # TTL 内は外部APIが落ちていても呼ばないので、stale にならない。
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    route, _ = _seed(open_meteo, forecast("tokyo"), cache, clock)

    clock.now = FIXED_NOW + timedelta(seconds=TTL_S - 1)
    hit = _call(City.TOKYO, clock, cache)

    assert route.call_count == 1
    assert (hit.cached, hit.stale) == (True, False)


def test_service_stale_reselects_hourly_by_now(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # stale で返すときも、過ぎた時刻を先頭に残さない。
    raw = forecast("tokyo")
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    _, first = _seed(open_meteo, raw, cache, clock)

    # 取得（21:11:10）の 2 時間後。次の正時は 10-20 の 0:00。
    clock.now = FIXED_NOW + timedelta(hours=2)
    stale = _call(City.TOKYO, clock, cache)

    assert stale.stale is True
    assert first.hourly[0].time == datetime(2026, 10, 19, 22, 0, tzinfo=UTC)
    assert stale.hourly[0].time == datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    assert len(stale.hourly) == 24
    assert stale.hourly[:22] == first.hourly[2:]
    # 値は fixture の同じ時刻の行。
    row = raw["hourly"]["time"].index(int(stale.hourly[0].time.timestamp()))
    assert stale.hourly[0].temperature_c == raw["hourly"]["temperature_2m"][row]
    last_row = raw["hourly"]["time"].index(int(stale.hourly[-1].time.timestamp()))
    assert last_row == row + 23
    assert stale.hourly[-1].temperature_c == raw["hourly"]["temperature_2m"][last_row]


def test_service_stale_does_not_overwrite_entry(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    raw = forecast("tokyo")
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    route, _ = _seed(open_meteo, raw, cache, clock)
    stored = _read(cache, TOKYO_KEY)

    clock.now = FIXED_NOW + timedelta(minutes=20)
    stale = _call(City.TOKYO, clock, cache)

    # stale を返しても保存値は元のまま（取得時刻を新しくしない）。
    assert stale.stale is True
    assert _read(cache, TOKYO_KEY) == stored

    # 外部APIが直れば、次は取得し直す。
    route.mock(return_value=_ok(raw))
    recovered_at = FIXED_NOW + timedelta(minutes=25)
    clock.now = recovered_at
    recovered = _call(City.TOKYO, clock, cache)
    again = _call(City.TOKYO, clock, cache)

    assert (recovered.cached, recovered.stale) == (False, False)
    assert recovered.fetched_at == recovered_at.replace(microsecond=0)
    assert (again.cached, again.stale) == (True, False)
    assert again.fetched_at == recovered_at.replace(microsecond=0)


@pytest.mark.parametrize(
    "broken",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"current": {}}),
        httpx.Response(400, json={"error": True, "reason": "test reason"}),
        httpx.Response(429),
    ],
)
def test_service_invalid_response_returns_stale(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast], broken: httpx.Response
) -> None:
    # 通信の失敗だけでなく、壊れた応答・4xx のときも保存値を返す（2026-10-12 決定）。
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    route, _ = _seed(open_meteo, forecast("tokyo"), cache, clock)
    stored = _read(cache, TOKYO_KEY)
    route.mock(return_value=broken)

    clock.now = FIXED_NOW + timedelta(minutes=20)
    response = _call(City.TOKYO, clock, cache)

    assert response.stale is True
    assert response.fetched_at == FETCHED_AT
    # リトライしない種類の失敗なので、呼び出しは 1 回だけ増える。
    assert route.call_count == 2
    # 壊れた応答で保存値を上書きしない。
    assert _read(cache, TOKYO_KEY) == stored


@pytest.mark.parametrize(
    "stored",
    [
        "not json",
        "{}",
        '{"fetched_at": "2026-10-12T15:00:00+00:00", "raw": {}}',
        '{"fetched_at": "2026-10-12T15:00:00", "raw": {}}',
    ],
)
def test_service_corrupted_entry_is_not_returned_as_stale(
    open_meteo: respx.MockRouter, stored: str
) -> None:
    open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(500))
    cache = MemoryCache()
    _write(cache, TOKYO_KEY, stored)

    # 壊れた保存値で 500 にせず、使えるキャッシュなしとして扱う。
    with pytest.raises(UpstreamError):
        _call(City.TOKYO, FakeClock(FIXED_NOW), cache)


def test_service_entry_from_future_is_not_returned_as_stale(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # 時計が戻った場合など。いまより後に取得したことになっている保存値は使わない。
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW + timedelta(minutes=30))
    _seed(open_meteo, forecast("tokyo"), cache, clock)

    clock.now = FIXED_NOW
    with pytest.raises(UpstreamError):
        _call(City.TOKYO, clock, cache)


def test_service_entry_invalid_at_now_is_not_returned_as_stale(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # 取得時は返さない範囲（25 件目）にあった null が、正時をまたいで返す範囲に入る場合。
    raw = forecast("tokyo")
    first_row = raw["hourly"]["time"].index(int(datetime(2026, 10, 19, 22, tzinfo=UTC).timestamp()))
    with_null = copy.deepcopy(raw)
    with_null["hourly"]["temperature_2m"][first_row + 24] = None
    cache = MemoryCache()
    clock = FakeClock(datetime(2026, 10, 19, 21, 55, tzinfo=UTC))
    _seed(open_meteo, with_null, cache, clock)

    clock.now = datetime(2026, 10, 19, 22, 20, tzinfo=UTC)
    with pytest.raises(UpstreamError):
        _call(City.TOKYO, clock, cache)


@pytest.mark.parametrize("stale_max_age_s", [STALE_MAX_AGE_S, 3600])
def test_service_stores_with_stale_max_age(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast], stale_max_age_s: int
) -> None:
    # 保存先の期限は TTL ではなく stale の上限（TTL を過ぎた値を stale 用に残すため）。
    open_meteo.get(FORECAST_URL).mock(return_value=_ok(forecast("tokyo")))
    cache = _RecordingCache()

    _call(City.TOKYO, FakeClock(FIXED_NOW), cache, stale_max_age_s=stale_max_age_s)

    assert cache.expiries == [stale_max_age_s]


def test_service_respects_configured_stale_max_age(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    _seed(open_meteo, forecast("tokyo"), cache, clock)

    clock.now = FIXED_NOW + timedelta(seconds=1800)
    at_limit = _call(City.TOKYO, clock, cache, stale_max_age_s=1800)
    clock.now = FIXED_NOW + timedelta(seconds=1801)
    with pytest.raises(UpstreamError):
        _call(City.TOKYO, clock, cache, stale_max_age_s=1800)

    assert at_limit.stale is True


def test_service_cache_read_failure_and_upstream_failure_raises(
    open_meteo: respx.MockRouter,
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(UpstreamError):
        _call(City.TOKYO, FakeClock(FIXED_NOW), _FailingReadCache())

    assert route.call_count == MAX_ATTEMPTS


def test_service_stale_is_logged(
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    _seed(open_meteo, forecast("tokyo"), cache, clock)

    clock.now = FIXED_NOW + timedelta(minutes=20)
    with caplog.at_level(logging.WARNING):
        _call(City.TOKYO, clock, cache)

    stale_logs = [
        record
        for record in caplog.records
        if record.name == "app.services.weather" and "stale" in record.getMessage()
    ]
    assert len(stale_logs) == 1
    assert stale_logs[0].levelno == logging.WARNING
    # アプリのログだけを見る（httpx 自身の INFO ログは、ほかのテストがログ設定を
    # 変えた後だと、最初の取得のぶんが記録に入るため）。
    app_logs = "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("app.")
    )
    assert "open-meteo.com" not in app_logs
    # 保存値の中身を出さない。
    assert "temperature_2m" not in app_logs
