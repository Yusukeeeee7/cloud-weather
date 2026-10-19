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

# spec.md「6. キャッシュ」の TTL 15 分。stale は最大 6 時間前まで。
TTL_S = 900
STALE_MAX_AGE_S = 21600
TOKYO_KEY = "weather:tokyo"
BERLIN_KEY = "weather:berlin"


class _FailingReadCache:
    """読み出しが必ず失敗するキャッシュ。書き込みは記録する。"""

    def __init__(self) -> None:
        self.written: list[str] = []

    async def get(self, key: str) -> str | None:
        # 例外の文面に接続先が入っていても、ログに出ないことを確かめるためのダミー。
        raise CacheError("redis://dummy-host:6379 is unreachable")

    async def set(self, key: str, value: str, expire_s: int) -> None:
        self.written.append(key)

    async def close(self) -> None:
        return None


class _FailingWriteCache:
    """書き込みが必ず失敗するキャッシュ。読み出しは常に「ない」。"""

    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, expire_s: int) -> None:
        raise CacheError("redis://dummy-host:6379 is unreachable")

    async def close(self) -> None:
        return None


def _call(city: City, clock: FakeClock, cache: Cache, ttl_s: int = TTL_S) -> WeatherResponse:
    async def run() -> WeatherResponse:
        settings = Settings(_env_file=None)
        async with build_http_client(settings) as http:
            client = OpenMeteoClient(http, settings)
            return await get_weather(city, client, clock, cache, ttl_s, STALE_MAX_AGE_S)

    return asyncio.run(run())


def _read(cache: Cache, key: str) -> str | None:
    return asyncio.run(cache.get(key))


def _write(cache: Cache, key: str, value: str) -> None:
    asyncio.run(cache.set(key, value, TTL_S))


def _mock_ok(open_meteo: respx.MockRouter, raw: RawForecast) -> respx.Route:
    return open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=raw))


def test_service_miss_fetches_and_stores(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    route = _mock_ok(open_meteo, forecast("tokyo"))
    cache = MemoryCache()
    assert _read(cache, TOKYO_KEY) is None

    response = _call(City.TOKYO, FakeClock(FIXED_NOW), cache)

    assert route.call_count == 1
    assert response.cached is False
    assert response.fetched_at == FIXED_NOW.replace(microsecond=0)
    assert _read(cache, TOKYO_KEY) is not None


def test_service_hit_within_ttl_does_not_call_upstream(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # 受け入れ条件：TTL 内は外部APIを呼ばない。
    route = _mock_ok(open_meteo, forecast("tokyo"))
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    first = _call(City.TOKYO, clock, cache)

    clock.now = FIXED_NOW + timedelta(minutes=5)
    second = _call(City.TOKYO, clock, cache)
    clock.now = FIXED_NOW + timedelta(minutes=10)
    third = _call(City.TOKYO, clock, cache)

    assert route.call_count == 1
    assert (first.cached, second.cached, third.cached) == (False, True, True)
    assert second.current == first.current
    assert second.daily == first.daily


def test_service_hit_keeps_original_fetched_at(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    _mock_ok(open_meteo, forecast("tokyo"))
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    _call(City.TOKYO, clock, cache)

    clock.now = FIXED_NOW + timedelta(minutes=7)
    hit = _call(City.TOKYO, clock, cache)

    # 返した時刻ではなく、外部APIから取得した時刻。
    assert hit.cached is True
    assert hit.fetched_at == FIXED_NOW.replace(microsecond=0)


@pytest.mark.parametrize(
    ("elapsed_s", "expected_calls", "expected_cached"),
    [(TTL_S - 1, 1, True), (TTL_S, 2, False), (TTL_S + 1, 2, False)],
)
def test_service_ttl_boundary(
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    elapsed_s: int,
    expected_calls: int,
    expected_cached: bool,
) -> None:
    # 15 分未満なら使う、15 分ちょうどから呼び直す（2026-10-12 決定）。
    route = _mock_ok(open_meteo, forecast("tokyo"))
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    _call(City.TOKYO, clock, cache)

    clock.now = FIXED_NOW + timedelta(seconds=elapsed_s)
    response = _call(City.TOKYO, clock, cache)

    assert route.call_count == expected_calls
    assert response.cached is expected_cached


def test_service_respects_configured_ttl(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    route = _mock_ok(open_meteo, forecast("tokyo"))
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    _call(City.TOKYO, clock, cache, ttl_s=60)

    clock.now = FIXED_NOW + timedelta(seconds=59)
    hit = _call(City.TOKYO, clock, cache, ttl_s=60)
    clock.now = FIXED_NOW + timedelta(seconds=60)
    miss = _call(City.TOKYO, clock, cache, ttl_s=60)

    assert (hit.cached, miss.cached) == (True, False)
    assert route.call_count == 2


def test_service_refetch_after_expiry_overwrites(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    route = _mock_ok(open_meteo, forecast("tokyo"))
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    _call(City.TOKYO, clock, cache)

    refetched_at = FIXED_NOW + timedelta(minutes=20)
    clock.now = refetched_at
    refetched = _call(City.TOKYO, clock, cache)
    clock.now = refetched_at + timedelta(minutes=5)
    hit = _call(City.TOKYO, clock, cache)

    assert route.call_count == 2
    assert refetched.cached is False
    assert refetched.fetched_at == refetched_at.replace(microsecond=0)
    assert hit.cached is True
    assert hit.fetched_at == refetched_at.replace(microsecond=0)


def test_service_cities_are_cached_separately(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(
        side_effect=[
            httpx.Response(200, json=forecast("tokyo")),
            httpx.Response(200, json=forecast("berlin")),
        ]
    )
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)
    _call(City.TOKYO, clock, cache)

    berlin = _call(City.BERLIN, clock, cache)
    tokyo_again = _call(City.TOKYO, clock, cache)
    berlin_again = _call(City.BERLIN, clock, cache)

    assert route.call_count == 2
    assert (berlin.city, berlin.cached) == ("berlin", False)
    assert (tokyo_again.city, tokyo_again.cached) == ("tokyo", True)
    assert (berlin_again.city, berlin_again.cached) == ("berlin", True)
    assert berlin_again.current == berlin.current
    assert tokyo_again.timezone == "Asia/Tokyo"
    assert _read(cache, TOKYO_KEY) is not None
    assert _read(cache, BERLIN_KEY) is not None


def test_service_hit_reselects_hourly_by_now(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # 取得後に正時をまたいだら、過ぎた時刻を先頭に残さず、次の正時から 24 件を返す。
    raw = forecast("tokyo")
    route = _mock_ok(open_meteo, raw)
    cache = MemoryCache()
    fetched_at = datetime(2026, 10, 19, 18, 55, tzinfo=UTC)
    clock = FakeClock(fetched_at)
    miss = _call(City.TOKYO, clock, cache)

    clock.now = datetime(2026, 10, 19, 19, 5, tzinfo=UTC)
    hit = _call(City.TOKYO, clock, cache)

    assert route.call_count == 1
    assert hit.cached is True
    assert hit.fetched_at == fetched_at
    assert miss.hourly[0].time == datetime(2026, 10, 19, 19, 0, tzinfo=UTC)
    assert hit.hourly[0].time == datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
    assert len(hit.hourly) == 24
    assert hit.hourly[:23] == miss.hourly[1:]
    # 値は fixture の同じ時刻の行。
    row = raw["hourly"]["time"].index(int(hit.hourly[0].time.timestamp()))
    assert hit.hourly[0].temperature_c == raw["hourly"]["temperature_2m"][row]
    last_row = raw["hourly"]["time"].index(int(hit.hourly[-1].time.timestamp()))
    assert last_row == row + 23
    assert hit.hourly[-1].temperature_c == raw["hourly"]["temperature_2m"][last_row]


@pytest.mark.parametrize(
    ("upstream", "calls_per_request"),
    [
        # タイムアウトと 5xx はリトライする（最初の 1 回 + リトライ 2 回。#6）。
        ({"side_effect": httpx.ReadTimeout}, 3),
        ({"return_value": httpx.Response(500)}, 3),
        ({"return_value": httpx.Response(200, content=b"not json")}, 1),
    ],
)
def test_service_upstream_failure_is_not_cached(
    open_meteo: respx.MockRouter, upstream: dict[str, object], calls_per_request: int
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(**upstream)
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW)

    with pytest.raises(UpstreamError):
        _call(City.TOKYO, clock, cache)
    assert _read(cache, TOKYO_KEY) is None
    with pytest.raises(UpstreamError):
        _call(City.TOKYO, clock, cache)

    # 失敗を保存していないので、次の呼び出しでまた外部APIを呼ぶ。
    assert route.call_count == 2 * calls_per_request


@pytest.mark.parametrize("section", ["current", "hourly", "daily"])
def test_service_invalid_upstream_response_is_not_cached(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast], section: str
) -> None:
    raw = forecast("tokyo")
    del raw[section]
    route = _mock_ok(open_meteo, raw)
    cache = MemoryCache()

    with pytest.raises(UpstreamError):
        _call(City.TOKYO, FakeClock(FIXED_NOW), cache)

    assert route.call_count == 1
    assert _read(cache, TOKYO_KEY) is None


@pytest.mark.parametrize(
    "stored",
    [
        "not json",
        "",
        "null",
        "[]",
        '"text"',
        "{}",
        '{"raw": {}}',
        '{"fetched_at": "2026-10-12T15:00:00+00:00"}',
        '{"fetched_at": "not a time", "raw": {}}',
        '{"fetched_at": 1791990000, "raw": {}}',
        '{"fetched_at": "2026-10-12T15:00:00+00:00", "raw": []}',
        # 新しいが、中身が外部APIの応答の形でない。
        '{"fetched_at": "2026-10-12T15:00:00+00:00", "raw": {}}',
        # タイムゾーンのない時刻は UTC と決めつけない。
        '{"fetched_at": "2026-10-12T15:00:00", "raw": {}}',
    ],
)
def test_service_corrupted_entry_is_refetched(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast], stored: str
) -> None:
    route = _mock_ok(open_meteo, forecast("tokyo"))
    cache = MemoryCache()
    _write(cache, TOKYO_KEY, stored)
    clock = FakeClock(FIXED_NOW)

    response = _call(City.TOKYO, clock, cache)
    again = _call(City.TOKYO, clock, cache)

    # 壊れた保存値で 500 にせず、呼び直して上書きする。
    assert response.cached is False
    assert response.fetched_at == FIXED_NOW.replace(microsecond=0)
    assert _read(cache, TOKYO_KEY) != stored
    assert again.cached is True
    assert route.call_count == 1


def test_service_entry_from_future_is_refetched(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # 時計が戻った場合など。いまより後に取得したことになっている保存値は使わない。
    route = _mock_ok(open_meteo, forecast("tokyo"))
    cache = MemoryCache()
    clock = FakeClock(FIXED_NOW + timedelta(minutes=5))
    _call(City.TOKYO, clock, cache)

    clock.now = FIXED_NOW
    response = _call(City.TOKYO, clock, cache)

    assert route.call_count == 2
    assert response.cached is False
    assert response.fetched_at == FIXED_NOW.replace(microsecond=0)


def test_service_entry_invalid_at_now_is_refetched(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # 取得時は返さない範囲（25 件目）にあった null が、正時をまたいで返す範囲に入る場合。
    good = forecast("tokyo")
    fetched_at = datetime(2026, 10, 19, 18, 55, tzinfo=UTC)
    first_row = good["hourly"]["time"].index(
        int(datetime(2026, 10, 19, 19, tzinfo=UTC).timestamp())
    )
    with_null = copy.deepcopy(good)
    with_null["hourly"]["temperature_2m"][first_row + 24] = None
    route = open_meteo.get(FORECAST_URL).mock(
        side_effect=[httpx.Response(200, json=with_null), httpx.Response(200, json=good)]
    )
    cache = MemoryCache()
    clock = FakeClock(fetched_at)
    first = _call(City.TOKYO, clock, cache)

    refetched_at = datetime(2026, 10, 19, 19, 5, tzinfo=UTC)
    clock.now = refetched_at
    second = _call(City.TOKYO, clock, cache)

    assert first.cached is False
    assert route.call_count == 2
    assert second.cached is False
    assert second.fetched_at == refetched_at
    assert second.hourly[-1].temperature_c == good["hourly"]["temperature_2m"][first_row + 24]


def test_service_cache_read_failure_falls_back_to_upstream(
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    caplog: pytest.LogCaptureFixture,
) -> None:
    route = _mock_ok(open_meteo, forecast("tokyo"))
    cache = _FailingReadCache()

    with caplog.at_level(logging.WARNING):
        response = _call(City.TOKYO, FakeClock(FIXED_NOW), cache)

    assert route.call_count == 1
    assert response.cached is False
    assert response.city == "tokyo"
    # 読めなくても、取得した値の保存は試みる。
    assert cache.written == [TOKYO_KEY]
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert any(record.name == "app.services.weather" for record in warnings)
    assert "redis://" not in caplog.text
    assert "dummy-host" not in caplog.text


def test_service_cache_write_failure_still_returns(
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    caplog: pytest.LogCaptureFixture,
) -> None:
    route = _mock_ok(open_meteo, forecast("tokyo"))

    with caplog.at_level(logging.WARNING):
        response = _call(City.TOKYO, FakeClock(FIXED_NOW), _FailingWriteCache())

    assert route.call_count == 1
    assert response.cached is False
    assert len(response.hourly) == 24
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert any(record.name == "app.services.weather" for record in warnings)
    assert "redis://" not in caplog.text
    assert "dummy-host" not in caplog.text
