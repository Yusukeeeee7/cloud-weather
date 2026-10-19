"""#15 日差し：`GET /sunshine`（外部APIは respx でモックする）。"""

import copy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from tests.app.cloud_base_fakes import row_of
from tests.conftest import (
    FIXED_NOW,
    FORECAST_URL,
    SUN_NOW,
    FakeClock,
    assert_error,
    iso,
    load_forecast,
    load_past_forecast,
    load_sun_forecast,
    mock_ok,
    seed_weather_cache,
)

RESPONSE_KEYS = {"city", "hourly"}
HOUR_KEYS = {"time", "sunshine_s", "direct_radiation_wm2", "diffuse_radiation_wm2"}
ITEMS = ("sunshine_duration", "direct_radiation", "diffuse_radiation")
# SUN_NOW（2026-10-14T12:21Z）より後の最初の正時。
FIRST = datetime(2026, 10, 14, 13, 0, tzinfo=UTC)
SIX_HOURS = timedelta(hours=6)


@pytest.fixture
def clock(client: TestClient) -> FakeClock:
    from app.main import app
    from app.routers.weather import get_clock

    fake = FakeClock(SUN_NOW)
    app.dependency_overrides[get_clock] = lambda: fake
    return fake


# --- 正常な応答 ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_sunshine_returns_spec_keys(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    raw = load_sun_forecast(city)
    route = mock_ok(open_meteo, raw)

    response = client.get("/sunshine", params={"city": city})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESPONSE_KEYS
    assert body["city"] == city
    assert len(body["hourly"]) == 24
    assert body["hourly"][0]["time"] == iso(FIRST)
    row = row_of(raw, FIRST)
    assert body["hourly"][0] == {
        "time": iso(FIRST),
        "sunshine_s": raw["hourly"]["sunshine_duration"][row],
        "direct_radiation_wm2": raw["hourly"]["direct_radiation"][row],
        "diffuse_radiation_wm2": raw["hourly"]["diffuse_radiation"][row],
    }
    for hour in body["hourly"]:
        assert set(hour) == HOUR_KEYS
    assert route.call_count == 1


def test_sunshine_times_match_weather(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    # /weather は風向が要る（#58）ので、風向のある fixture とその取得時刻を使う。
    mock_ok(open_meteo, load_forecast("tokyo"))
    clock.now = FIXED_NOW

    weather = client.get("/weather", params={"city": "tokyo"})
    sun = client.get("/sunshine", params={"city": "tokyo"})

    weather_times = [hour["time"] for hour in weather.json()["hourly"]]
    assert [hour["time"] for hour in sun.json()["hourly"]] == weather_times


# --- S6：city ---


def test_sunshine_city_default_is_tokyo(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    route = mock_ok(open_meteo, load_sun_forecast("tokyo"))

    response = client.get("/sunshine")

    assert response.json()["city"] == "tokyo"
    assert route.calls.last.request.url.params["timezone"] == "Asia/Tokyo"


@pytest.mark.parametrize("city", ["", "osaka", "TOKYO", " tokyo", "tokyo,berlin", "../etc"])
def test_sunshine_invalid_city(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    route = mock_ok(open_meteo, load_sun_forecast("tokyo"))

    response = client.get("/sunshine", params={"city": city})

    assert_error(response, 422, "invalid_city")
    assert route.call_count == 0


@pytest.mark.parametrize("status", [404, 500])
def test_sunshine_upstream_failure_without_cache_is_502(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, status: int
) -> None:
    open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(status))

    response = client.get("/sunshine", params={"city": "tokyo"})

    assert_error(response, 502, "upstream_error")


# --- S7〜S9：キャッシュ ---


def test_sunshine_shares_cache_with_weather(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    # /weather は風向が要る（#58）ので、風向のある fixture とその取得時刻を使う。
    route = mock_ok(open_meteo, load_forecast("tokyo"))
    clock.now = FIXED_NOW

    weather = client.get("/weather", params={"city": "tokyo"})
    clock.now = FIXED_NOW + timedelta(minutes=14, seconds=59)
    hit = client.get("/sunshine", params={"city": "tokyo"})
    calls_within_ttl = route.call_count
    clock.now = FIXED_NOW + timedelta(minutes=15)
    miss = client.get("/sunshine", params={"city": "tokyo"})

    assert (weather.status_code, hit.status_code, miss.status_code) == (200, 200, 200)
    assert calls_within_ttl == 1
    assert route.call_count == 2


def test_sunshine_refetches_when_cached_entry_lacks_items(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    # 3 項目を足す前の形（過去 24 時間を含む fixture）が保存されている場合。
    # /weather を通さずに保存先に入れる（/weather は風向が要る。#58）。
    seed_weather_cache(client, "tokyo", load_past_forecast("tokyo"), SUN_NOW)

    raw = load_sun_forecast("tokyo")
    route = mock_ok(open_meteo, raw)
    clock.now = SUN_NOW + timedelta(minutes=5)
    sun = client.get("/sunshine", params={"city": "tokyo"})
    again = client.get("/sunshine", params={"city": "tokyo"})

    assert sun.status_code == 200
    row = row_of(raw, FIRST)
    assert sun.json()["hourly"][0]["sunshine_s"] == raw["hourly"]["sunshine_duration"][row]
    assert again.json() == sun.json()
    # TTL の内の保存値を使わずに 1 回だけ呼び直し、その応答を保存する。
    assert route.call_count == 1


def test_sunshine_old_entry_and_upstream_failure_is_502(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    seed_weather_cache(client, "tokyo", load_past_forecast("tokyo"), SUN_NOW)
    open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(500))

    clock.now = SUN_NOW + timedelta(minutes=5)
    response = client.get("/sunshine", params={"city": "tokyo"})

    assert_error(response, 502, "upstream_error")


def test_sunshine_uses_stale_cache(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    raw = load_sun_forecast("tokyo")
    route = mock_ok(open_meteo, raw)
    client.get("/sunshine", params={"city": "tokyo"})
    route.mock(return_value=httpx.Response(500))

    clock.now = SUN_NOW + timedelta(hours=2)
    stale = client.get("/sunshine", params={"city": "tokyo"})
    clock.now = SUN_NOW + SIX_HOURS
    at_limit = client.get("/sunshine", params={"city": "tokyo"})
    clock.now = SUN_NOW + SIX_HOURS + timedelta(seconds=1)
    too_old = client.get("/sunshine", params={"city": "tokyo"})

    assert stale.status_code == 200
    assert set(stale.json()) == RESPONSE_KEYS
    later = FIRST + timedelta(hours=2)
    assert stale.json()["hourly"][0]["time"] == iso(later)
    assert (
        stale.json()["hourly"][0]["sunshine_s"]
        == raw["hourly"]["sunshine_duration"][row_of(raw, later)]
    )
    assert at_limit.status_code == 200
    assert at_limit.json()["hourly"][0]["time"] == iso(FIRST + SIX_HOURS)
    assert_error(too_old, 502, "upstream_error")


# --- S10：/weather は変わらない（Red にならない） ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_weather_unchanged_with_sunshine_items(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    # /weather は風向が要る（#58）ので、風向のある fixture とその取得時刻を使う。
    raw = load_forecast(city)
    without = copy.deepcopy(raw)
    for item in ITEMS:
        del without["hourly"][item]
        del without["hourly_units"][item]
    route = mock_ok(open_meteo, raw)
    clock.now = FIXED_NOW
    with_items = client.get("/weather", params={"city": city})

    # キャッシュを使わないように、TTL を過ぎてから 3 項目のない応答で取り直す。
    route.mock(return_value=httpx.Response(200, json=without))
    clock.now = FIXED_NOW + timedelta(minutes=15)
    without_items = client.get("/weather", params={"city": city})

    assert with_items.status_code == without_items.status_code == 200
    first, second = with_items.json(), without_items.json()
    assert set(first) == set(second)
    for key in ("city", "timezone", "current", "daily"):
        assert first[key] == second[key]
    assert first["hourly"] == second["hourly"]


# --- S11：OpenAPI ---


def test_openapi_documents_sunshine(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    operation = schema["paths"]["/sunshine"]["get"]
    assert {"200", "422", "502"} <= set(operation["responses"])
    text = str(schema["components"]["schemas"]["SunshineResponse"]) + str(
        schema["components"]["schemas"]["SunshineHour"]
    )
    assert "preceding hour" in text
