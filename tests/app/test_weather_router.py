import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import fakeredis
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.cache import Cache, MemoryCache, RedisCache
from tests.conftest import FIXED_NOW, FORECAST_URL, FakeClock, RawForecast

UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
LOCAL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TOP_LEVEL_KEYS = {
    "city",
    "timezone",
    "current",
    "hourly",
    "daily",
    "source",
    "fetched_at",
    "cached",
    "stale",
}
HOURLY_KEYS = {
    "time",
    "weather_code",
    "weather",
    "temperature_c",
    "precipitation_probability",
    "precipitation_mm",
    "cloud_cover",
}
DAILY_KEYS = {
    "date",
    "weather_code",
    "weather",
    "temperature_max_c",
    "temperature_min_c",
    "precipitation_probability_max",
    "precipitation_sum_mm",
    "sunrise",
    "sunset",
}
CURRENT_KEYS = {
    "time",
    "weather_code",
    "weather",
    "temperature_c",
    "apparent_temperature_c",
    "dew_point_c",
    "relative_humidity",
    "precipitation_mm",
    "wind_speed_ms",
    "cloud_cover",
}


def _mock_ok(open_meteo: respx.MockRouter, raw: RawForecast) -> respx.Route:
    return open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=raw))


@pytest.mark.parametrize(
    ("city", "timezone"), [("tokyo", "Asia/Tokyo"), ("berlin", "Europe/Berlin")]
)
def test_weather_returns_200_and_spec_shape(
    client: TestClient,
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    city: str,
    timezone: str,
) -> None:
    raw = forecast(city)
    route = _mock_ok(open_meteo, raw)

    response = client.get("/weather", params={"city": city})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == TOP_LEVEL_KEYS
    assert set(body["current"]) == CURRENT_KEYS
    assert set(body["current"]["cloud_cover"]) == {"total", "low", "mid", "high"}
    assert body["city"] == city
    assert body["timezone"] == timezone
    assert body["source"] == "open-meteo"
    assert body["current"]["temperature_c"] == raw["current"]["temperature_2m"]
    assert body["current"]["wind_speed_ms"] == raw["current"]["wind_speed_10m"]
    assert route.call_count == 1


def test_weather_times_are_utc_with_z(
    client: TestClient, open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    raw = forecast("tokyo")
    _mock_ok(open_meteo, raw)

    body = client.get("/weather", params={"city": "tokyo"}).json()

    assert UTC_Z.match(body["current"]["time"])
    expected = datetime.fromtimestamp(raw["current"]["time"], UTC)
    assert body["current"]["time"] == expected.strftime("%Y-%m-%dT%H:%M:%SZ")
    # conftest で固定した時計（2026-10-12T15:02:30.123456Z）の秒未満を切り捨てた値。
    assert body["fetched_at"] == "2026-10-12T15:02:30Z"


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_weather_returns_hourly_and_daily_shape(
    client: TestClient,
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    city: str,
) -> None:
    route = _mock_ok(open_meteo, forecast(city))

    response = client.get("/weather", params={"city": city})

    assert response.status_code == 200
    body = response.json()
    assert len(body["hourly"]) == 24
    assert len(body["daily"]) == 7
    for item in body["hourly"]:
        assert set(item) == HOURLY_KEYS
        assert set(item["cloud_cover"]) == {"total", "low", "mid", "high"}
    for item in body["daily"]:
        assert set(item) == DAILY_KEYS
    # cached は #5、stale は #6 で追加。
    assert body["cached"] is False
    assert body["stale"] is False
    assert route.call_count == 1


def test_weather_hourly_daily_times_format(
    client: TestClient,
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    forecast_iso8601: Callable[[str], RawForecast],
) -> None:
    _mock_ok(open_meteo, forecast("tokyo"))

    body = client.get("/weather", params={"city": "tokyo"}).json()

    assert all(UTC_Z.match(item["time"]) for item in body["hourly"])
    assert all(UTC_Z.match(item["sunrise"]) for item in body["daily"])
    assert all(UTC_Z.match(item["sunset"]) for item in body["daily"])
    assert all(LOCAL_DATE.match(item["date"]) for item in body["daily"])
    # 日付は現地の日付（同じ時刻に iso8601 形式で取得した Open-Meteo の応答の値）。
    assert [item["date"] for item in body["daily"]] == forecast_iso8601("tokyo")["daily"]["time"]


@pytest.mark.parametrize("section", ["hourly", "daily"])
def test_weather_broken_forecast_returns_502(
    client: TestClient,
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    section: str,
) -> None:
    # current が正しくても、hourly・daily が壊れていれば一部だけ返さず 502 にする。
    raw = forecast("tokyo")
    del raw[section]
    _mock_ok(open_meteo, raw)

    response = client.get("/weather", params={"city": "tokyo"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_error"


def test_weather_missing_city_defaults_to_tokyo(
    client: TestClient, open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    route = _mock_ok(open_meteo, forecast("tokyo"))

    response = client.get("/weather")

    assert response.status_code == 200
    assert response.json()["city"] == "tokyo"
    params = route.calls.last.request.url.params
    assert (float(params["latitude"]), float(params["longitude"])) == (35.55, 139.78)


@pytest.mark.parametrize(
    "city", ["osaka", "Tokyo", "TOKYO", "", " tokyo", "http://example.com", "tokyo,berlin"]
)
def test_weather_invalid_city_returns_422(
    client: TestClient, open_meteo: respx.MockRouter, city: str
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(200, json={}))

    response = client.get("/weather", params={"city": city})

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == "invalid_city"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert route.call_count == 0


@pytest.mark.parametrize(
    "upstream",
    [
        {"side_effect": httpx.ReadTimeout},
        {"side_effect": httpx.ConnectError},
        {"return_value": httpx.Response(500)},
        {"return_value": httpx.Response(200, content=b"not json")},
        {"return_value": httpx.Response(200, json={"current": {}})},
    ],
)
def test_weather_upstream_failure_returns_502(
    client: TestClient, open_meteo: respx.MockRouter, upstream: dict[str, object]
) -> None:
    open_meteo.get(FORECAST_URL).mock(**upstream)

    response = client.get("/weather", params={"city": "tokyo"})

    assert response.status_code == 502
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "upstream_error"
    message = body["error"]["message"]
    assert "open-meteo.com" not in message
    assert "Traceback" not in message
    assert "httpx" not in message


def test_weather_rejects_post(client: TestClient) -> None:
    response = client.post("/weather", params={"city": "tokyo"})

    assert response.status_code == 405


def test_health_still_ok(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("status", ["422", "502"])
def test_openapi_documents_error_format(client: TestClient, status: str) -> None:
    schema = client.get("/openapi.json").json()

    documented = schema["paths"]["/weather"]["get"]["responses"][status]
    ref = documented["content"]["application/json"]["schema"]["$ref"]
    assert ref == "#/components/schemas/ErrorResponse"


class _RecordingCache:
    """読み書きされたキーを記録するキャッシュ。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get(self, key: str) -> str | None:
        self.calls.append(("get", key))
        return None

    async def set(self, key: str, value: str, expire_s: int) -> None:
        self.calls.append(("set", key))

    async def close(self) -> None:
        return None


def _use_cache(cache: Cache) -> None:
    from app.main import app
    from app.routers.weather import get_cache

    app.dependency_overrides[get_cache] = lambda: cache


def _use_clock(clock: FakeClock) -> None:
    from app.main import app
    from app.routers.weather import get_clock

    app.dependency_overrides[get_clock] = lambda: clock


def _build_backend(backend: str) -> Cache | None:
    if backend == "redis":
        # 実物の Redis は使わない。保存先を替えても API の動きが同じことを確かめる。
        return RedisCache(fakeredis.FakeAsyncRedis(decode_responses=True))
    # None のときは、アプリが既定の設定で作ったキャッシュ（メモリ）をそのまま使う。
    return None


@pytest.mark.parametrize("backend", ["default", "redis"])
@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_weather_second_request_is_cached(
    client: TestClient,
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    city: str,
    backend: str,
) -> None:
    route = _mock_ok(open_meteo, forecast(city))
    cache = _build_backend(backend)
    if cache is not None:
        _use_cache(cache)
    clock = FakeClock(FIXED_NOW)
    _use_clock(clock)

    first = client.get("/weather", params={"city": city})
    clock.now = FIXED_NOW + timedelta(minutes=5)
    second = client.get("/weather", params={"city": city})

    assert (first.status_code, second.status_code) == (200, 200)
    assert route.call_count == 1
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert second.json()["fetched_at"] == first.json()["fetched_at"] == "2026-10-12T15:02:30Z"
    assert second.json()["current"] == first.json()["current"]
    assert second.json()["daily"] == first.json()["daily"]


def test_weather_default_cache_is_memory(client: TestClient) -> None:
    from app.main import app

    assert isinstance(app.state.weather_cache, MemoryCache)


def test_weather_refetches_after_ttl(
    client: TestClient, open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    route = _mock_ok(open_meteo, forecast("tokyo"))
    clock = FakeClock(FIXED_NOW)
    _use_clock(clock)
    client.get("/weather", params={"city": "tokyo"})

    # 既定の TTL（15 分）ちょうど。
    clock.now = FIXED_NOW + timedelta(minutes=15)
    body = client.get("/weather", params={"city": "tokyo"}).json()

    assert route.call_count == 2
    assert body["cached"] is False
    assert body["fetched_at"] == "2026-10-12T15:17:30Z"


def test_weather_cached_response_keeps_spec_shape(
    client: TestClient, open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    _mock_ok(open_meteo, forecast("tokyo"))
    client.get("/weather", params={"city": "tokyo"})

    body = client.get("/weather", params={"city": "tokyo"}).json()

    assert body["cached"] is True
    assert set(body) == TOP_LEVEL_KEYS
    assert body["stale"] is False
    assert len(body["hourly"]) == 24
    assert len(body["daily"]) == 7
    assert UTC_Z.match(body["fetched_at"])


def test_weather_uses_city_key(
    client: TestClient, open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    _mock_ok(open_meteo, forecast("berlin"))
    cache = _RecordingCache()
    _use_cache(cache)

    client.get("/weather", params={"city": "berlin"})

    # キーは spec.md「6. キャッシュ」の weather:{city}。
    assert cache.calls == [("get", "weather:berlin"), ("set", "weather:berlin")]


@pytest.mark.parametrize("city", ["osaka", "Tokyo", "", "weather:tokyo", "tokyo\nberlin", "*"])
def test_weather_invalid_city_does_not_touch_cache(
    client: TestClient, open_meteo: respx.MockRouter, city: str
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(200, json={}))
    cache = _RecordingCache()
    _use_cache(cache)

    response = client.get("/weather", params={"city": city})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_city"
    assert cache.calls == []
    assert route.call_count == 0


def test_weather_upstream_error_then_success(
    client: TestClient, open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(
        # 1 回目のリクエストはリトライを使い切るまで失敗する（最初の 1 回 + リトライ 2 回。#6）。
        side_effect=[
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(200, json=forecast("tokyo")),
        ]
    )

    failed = client.get("/weather", params={"city": "tokyo"})
    recovered = client.get("/weather", params={"city": "tokyo"})

    # 失敗は保存されないので、外部APIが直れば次のリクエストで 200 になる。
    assert failed.status_code == 502
    assert recovered.status_code == 200
    assert recovered.json()["cached"] is False
    assert route.call_count == 4


def test_weather_cache_failure_still_returns_200(
    client: TestClient, open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # キャッシュが故障しても API は止めない（2026-10-12 決定）。
    route = _mock_ok(open_meteo, forecast("tokyo"))
    server = fakeredis.FakeServer()
    server.connected = False
    _use_cache(RedisCache(fakeredis.FakeAsyncRedis(server=server, decode_responses=True)))

    first = client.get("/weather", params={"city": "tokyo"})
    second = client.get("/weather", params={"city": "tokyo"})

    assert (first.status_code, second.status_code) == (200, 200)
    assert (first.json()["cached"], second.json()["cached"]) == (False, False)
    assert route.call_count == 2


def test_weather_uses_configured_ttl(
    client: TestClient, open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # CACHE_TTL_S の値が、リクエストの処理まで届くこと（既定の 900 秒の直書きにならない）。
    from app.config import Settings, get_settings
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, cache_ttl_s=60)
    route = _mock_ok(open_meteo, forecast("tokyo"))
    clock = FakeClock(FIXED_NOW)
    _use_clock(clock)
    client.get("/weather", params={"city": "tokyo"})

    clock.now = FIXED_NOW + timedelta(seconds=59)
    hit = client.get("/weather", params={"city": "tokyo"}).json()
    clock.now = FIXED_NOW + timedelta(seconds=60)
    miss = client.get("/weather", params={"city": "tokyo"}).json()

    assert (hit["cached"], miss["cached"]) == (True, False)
    assert route.call_count == 2


# --- #6 エラー処理（リトライ・stale・502） ---

SIX_HOURS = timedelta(hours=6)


def _use_settings(**values: int) -> None:
    from app.config import Settings, get_settings
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, **values)


@pytest.mark.parametrize("backend", ["default", "redis"])
def test_weather_returns_stale_when_upstream_fails(
    client: TestClient,
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    backend: str,
) -> None:
    # 受け入れ条件：外部APIが失敗しても、6 時間以内の保存値があれば stale: true で 200。
    route = _mock_ok(open_meteo, forecast("tokyo"))
    cache = _build_backend(backend)
    if cache is not None:
        _use_cache(cache)
    clock = FakeClock(FIXED_NOW)
    _use_clock(clock)
    first = client.get("/weather", params={"city": "tokyo"})

    route.mock(return_value=httpx.Response(500))
    clock.now = FIXED_NOW + timedelta(minutes=20)
    second = client.get("/weather", params={"city": "tokyo"})

    assert (first.status_code, second.status_code) == (200, 200)
    assert (first.json()["cached"], first.json()["stale"]) == (False, False)
    body = second.json()
    assert set(body) == TOP_LEVEL_KEYS
    assert (body["cached"], body["stale"]) == (True, True)
    assert body["fetched_at"] == first.json()["fetched_at"] == "2026-10-12T15:02:30Z"
    assert body["current"] == first.json()["current"]
    assert len(body["hourly"]) == 24
    assert len(body["daily"]) == 7
    # 最初の取得 1 回 + 失敗した 3 回（最初の 1 回 + リトライ 2 回）。
    assert route.call_count == 4


@pytest.mark.parametrize(
    ("elapsed", "expected_status"),
    [(SIX_HOURS, 200), (SIX_HOURS + timedelta(seconds=1), 502)],
)
def test_weather_stale_older_than_limit_returns_502(
    client: TestClient,
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    elapsed: timedelta,
    expected_status: int,
) -> None:
    # spec.md「6. キャッシュ」：最大 6 時間前まで。それより古ければ 502。
    route = _mock_ok(open_meteo, forecast("tokyo"))
    clock = FakeClock(FIXED_NOW)
    _use_clock(clock)
    client.get("/weather", params={"city": "tokyo"})

    route.mock(return_value=httpx.Response(500))
    clock.now = FIXED_NOW + elapsed
    response = client.get("/weather", params={"city": "tokyo"})

    assert response.status_code == expected_status
    body = response.json()
    if expected_status == 200:
        assert body["stale"] is True
    else:
        assert set(body) == {"error"}
        assert body["error"]["code"] == "upstream_error"


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ConnectError, httpx.Response(503)])
def test_weather_retries_then_returns_200(
    client: TestClient,
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    waits: list[float],
    failure: object,
) -> None:
    # 受け入れ条件：タイムアウト・5xx でリトライ。1 回失敗しても、次で取れれば通常の応答。
    route = open_meteo.get(FORECAST_URL).mock(
        side_effect=[failure, httpx.Response(200, json=forecast("tokyo"))]
    )

    response = client.get("/weather", params={"city": "tokyo"})

    assert response.status_code == 200
    assert (response.json()["cached"], response.json()["stale"]) == (False, False)
    assert route.call_count == 2
    assert waits == [0.5]


def test_weather_failure_without_cache_returns_502_after_retries(
    client: TestClient, open_meteo: respx.MockRouter
) -> None:
    # 受け入れ条件：外部APIの失敗かつ使えるキャッシュがなければ 502。
    route = open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(500))

    response = client.get("/weather", params={"city": "tokyo"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_error"
    assert route.call_count == 3


def test_weather_stale_is_per_city(
    client: TestClient, open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # 東京の保存値を、ベルリンの stale として返さない。
    route = _mock_ok(open_meteo, forecast("tokyo"))
    clock = FakeClock(FIXED_NOW)
    _use_clock(clock)
    client.get("/weather", params={"city": "tokyo"})

    route.mock(return_value=httpx.Response(500))
    clock.now = FIXED_NOW + timedelta(minutes=20)
    berlin = client.get("/weather", params={"city": "berlin"})
    tokyo = client.get("/weather", params={"city": "tokyo"})

    assert berlin.status_code == 502
    assert tokyo.status_code == 200
    assert (tokyo.json()["city"], tokyo.json()["stale"]) == ("tokyo", True)


def test_weather_recovers_after_stale(
    client: TestClient, open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    route = _mock_ok(open_meteo, forecast("tokyo"))
    clock = FakeClock(FIXED_NOW)
    _use_clock(clock)
    client.get("/weather", params={"city": "tokyo"})

    route.mock(return_value=httpx.Response(500))
    clock.now = FIXED_NOW + timedelta(minutes=20)
    stale = client.get("/weather", params={"city": "tokyo"}).json()
    route.mock(return_value=httpx.Response(200, json=forecast("tokyo")))
    clock.now = FIXED_NOW + timedelta(minutes=25)
    recovered = client.get("/weather", params={"city": "tokyo"}).json()

    assert stale["stale"] is True
    assert (recovered["cached"], recovered["stale"]) == (False, False)
    assert recovered["fetched_at"] == "2026-10-12T15:27:30Z"


def test_weather_uses_configured_stale_max_age(
    client: TestClient, open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    # CACHE_STALE_MAX_AGE_S の値が、リクエストの処理まで届くこと（6 時間の直書きにならない）。
    _use_settings(cache_ttl_s=60, cache_stale_max_age_s=120)
    route = _mock_ok(open_meteo, forecast("tokyo"))
    clock = FakeClock(FIXED_NOW)
    _use_clock(clock)
    client.get("/weather", params={"city": "tokyo"})

    route.mock(return_value=httpx.Response(500))
    clock.now = FIXED_NOW + timedelta(seconds=120)
    at_limit = client.get("/weather", params={"city": "tokyo"})
    clock.now = FIXED_NOW + timedelta(seconds=121)
    over_limit = client.get("/weather", params={"city": "tokyo"})

    assert at_limit.status_code == 200
    assert at_limit.json()["stale"] is True
    assert over_limit.status_code == 502


def test_openapi_includes_stale(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    weather = schema["components"]["schemas"]["WeatherResponse"]
    assert weather["properties"]["stale"]["type"] == "boolean"
    assert "stale" in weather["required"]
