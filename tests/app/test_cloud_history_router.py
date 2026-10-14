"""#15 過去 24 時間の雲量：`GET /cloud-history`（外部APIは respx でモックする）。"""

import copy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from tests.app.cloud_base_fakes import expected_baseline_m, fake_model
from tests.conftest import (
    FORECAST_URL,
    PAST_NOW,
    FakeClock,
    RawForecast,
    load_past_forecast,
)

RESPONSE_KEYS = {"city", "hourly"}
HOUR_KEYS = {"time", "cloud_cover"}
CLOUD_COVER_KEYS = {"total", "low", "mid", "high"}
# PAST_NOW（2026-10-14T09:18Z）以前の最も近い正時。
LATEST = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
SIX_HOURS = timedelta(hours=6)


def _iso(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mock_ok(open_meteo: respx.MockRouter, raw: RawForecast) -> respx.Route:
    return open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=raw))


def _use_clock(clock: FakeClock) -> None:
    from app.main import app
    from app.routers.weather import get_clock

    app.dependency_overrides[get_clock] = lambda: clock


def _assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


def _without_past_hours(raw: RawForecast) -> RawForecast:
    """過去の時間を足す前の形（hourly が取得時の正時から始まる）。fixture の先頭 24 行を除く。"""
    changed = copy.deepcopy(raw)
    changed["hourly"] = {name: column[24:] for name, column in raw["hourly"].items()}
    return changed


@pytest.fixture
def clock(client: TestClient) -> FakeClock:
    """過去 24 時間を含む fixture を取得した時刻に合わせた時計。"""
    fake = FakeClock(PAST_NOW)
    _use_clock(fake)
    return fake


def _row_of(raw: RawForecast, at: datetime) -> int:
    times: list[int] = raw["hourly"]["time"]
    return times.index(int(at.timestamp()))


# --- 正常な応答と city ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_history_returns_spec_keys(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    raw = load_past_forecast(city)
    route = _mock_ok(open_meteo, raw)

    response = client.get("/cloud-history", params={"city": city})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESPONSE_KEYS
    assert body["city"] == city
    assert len(body["hourly"]) == 24
    assert body["hourly"][0]["time"] == _iso(LATEST - timedelta(hours=23))
    assert body["hourly"][-1]["time"] == _iso(LATEST)
    for hour in body["hourly"]:
        assert set(hour) == HOUR_KEYS
        assert set(hour["cloud_cover"]) == CLOUD_COVER_KEYS
    last = _row_of(raw, LATEST)
    assert body["hourly"][-1]["cloud_cover"] == {
        "total": raw["hourly"]["cloud_cover"][last],
        "low": raw["hourly"]["cloud_cover_low"][last],
        "mid": raw["hourly"]["cloud_cover_mid"][last],
        "high": raw["hourly"]["cloud_cover_high"][last],
    }
    assert route.call_count == 1


def test_history_city_default_is_tokyo(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    route = _mock_ok(open_meteo, load_past_forecast("tokyo"))

    response = client.get("/cloud-history")

    assert response.status_code == 200
    assert response.json()["city"] == "tokyo"
    assert route.calls.last.request.url.params["timezone"] == "Asia/Tokyo"


# --- 11：不正な city ---


@pytest.mark.parametrize("city", ["", "osaka", "TOKYO", " tokyo", "tokyo,berlin", "../etc"])
def test_history_invalid_city(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    route = _mock_ok(open_meteo, load_past_forecast("tokyo"))

    response = client.get("/cloud-history", params={"city": city})

    _assert_error(response, 422, "invalid_city")
    assert route.call_count == 0


# --- 外部APIの失敗 ---


@pytest.mark.parametrize("status", [404, 500])
def test_history_upstream_failure_without_cache_is_502(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, status: int
) -> None:
    open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(status))

    response = client.get("/cloud-history", params={"city": "tokyo"})

    _assert_error(response, 502, "upstream_error")


def test_history_null_in_window_is_502(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    raw = copy.deepcopy(load_past_forecast("tokyo"))
    raw["hourly"]["cloud_cover_mid"][_row_of(raw, LATEST - timedelta(hours=5))] = None
    _mock_ok(open_meteo, raw)

    response = client.get("/cloud-history", params={"city": "tokyo"})

    _assert_error(response, 502, "upstream_error")


# --- 8：キャッシュ ---


def test_history_uses_cache_within_ttl(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    # /weather が保存した値を使う。TTL（15 分）ちょうどから呼び直す。
    route = _mock_ok(open_meteo, load_past_forecast("tokyo"))
    weather = client.get("/weather", params={"city": "tokyo"})
    clock.now = PAST_NOW + timedelta(minutes=14, seconds=59)
    hit = client.get("/cloud-history", params={"city": "tokyo"})
    calls_after_hit = route.call_count
    clock.now = PAST_NOW + timedelta(minutes=15)
    miss = client.get("/cloud-history", params={"city": "tokyo"})

    assert (weather.status_code, hit.status_code, miss.status_code) == (200, 200, 200)
    assert calls_after_hit == 1
    assert route.call_count == 2


def test_history_selects_rows_again_when_served_from_cache(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    # 09:55 に取得した保存値を 10:05 に使うときは、最後が 10:00 になる。
    route = _mock_ok(open_meteo, load_past_forecast("tokyo"))
    clock.now = datetime(2026, 10, 14, 9, 55, tzinfo=UTC)
    first = client.get("/cloud-history", params={"city": "tokyo"})
    clock.now = datetime(2026, 10, 14, 10, 5, tzinfo=UTC)
    second = client.get("/cloud-history", params={"city": "tokyo"})

    assert route.call_count == 1
    assert first.json()["hourly"][-1]["time"] == "2026-10-14T09:00:00Z"
    assert second.json()["hourly"][-1]["time"] == "2026-10-14T10:00:00Z"
    assert second.json()["hourly"][0]["time"] == "2026-10-13T11:00:00Z"


# --- 9：過去の時間のない保存値 ---


def test_history_refetches_when_cached_value_lacks_past_hours(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    raw = load_past_forecast("tokyo")
    route = _mock_ok(open_meteo, _without_past_hours(raw))
    weather = client.get("/weather", params={"city": "tokyo"})
    assert (weather.status_code, route.call_count) == (200, 1)

    route.mock(return_value=httpx.Response(200, json=raw))
    clock.now = PAST_NOW + timedelta(minutes=5)
    history = client.get("/cloud-history", params={"city": "tokyo"})
    again = client.get("/cloud-history", params={"city": "tokyo"})

    assert history.status_code == 200
    assert history.json()["hourly"][0]["time"] == _iso(LATEST - timedelta(hours=23))
    # 呼び直した応答は保存され、次は外部APIを呼ばない。
    assert again.json() == history.json()
    assert route.call_count == 2


def test_history_old_value_and_upstream_failure_is_502(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    route = _mock_ok(open_meteo, _without_past_hours(load_past_forecast("tokyo")))
    client.get("/weather", params={"city": "tokyo"})

    route.mock(return_value=httpx.Response(500))
    clock.now = PAST_NOW + timedelta(minutes=5)
    response = client.get("/cloud-history", params={"city": "tokyo"})

    _assert_error(response, 502, "upstream_error")


# --- 10：stale ---


def test_history_returns_stale_on_upstream_error(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    route = _mock_ok(open_meteo, load_past_forecast("tokyo"))
    client.get("/cloud-history", params={"city": "tokyo"})
    route.mock(return_value=httpx.Response(500))

    clock.now = PAST_NOW + timedelta(hours=2)
    stale = client.get("/cloud-history", params={"city": "tokyo"})
    # 上限（6 時間）ちょうどは返す。過ぎたら 502。
    clock.now = PAST_NOW + SIX_HOURS
    at_limit = client.get("/cloud-history", params={"city": "tokyo"})
    clock.now = PAST_NOW + SIX_HOURS + timedelta(seconds=1)
    too_old = client.get("/cloud-history", params={"city": "tokyo"})

    assert stale.status_code == 200
    # 応答のキーは増やさない。時刻は、いまの時刻で選び直す。
    assert set(stale.json()) == RESPONSE_KEYS
    assert stale.json()["hourly"][-1]["time"] == _iso(LATEST + timedelta(hours=2))
    assert at_limit.status_code == 200
    assert at_limit.json()["hourly"][-1]["time"] == _iso(LATEST + SIX_HOURS)
    _assert_error(too_old, 502, "upstream_error")


# --- 12：/weather と /cloud-base は変わらない（Red にならない） ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_weather_and_cloud_base_unchanged_with_past_hours(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    from app.main import app
    from app.routers.cloud_base import get_cloud_base_model

    raw = load_past_forecast(city)
    _mock_ok(open_meteo, raw)
    fake, _ = fake_model(850.0)
    app.dependency_overrides[get_cloud_base_model] = lambda: fake

    weather = client.get("/weather", params={"city": city})
    cloud_base = client.get("/cloud-base", params={"city": city})

    assert weather.status_code == 200
    hourly = weather.json()["hourly"]
    # 現在（09:18Z）より後の最初の正時から 24 件。先頭の 24 行（過去）は使わない。
    assert len(hourly) == 24
    first = LATEST + timedelta(hours=1)
    assert hourly[0]["time"] == _iso(first)
    assert hourly[0]["temperature_c"] == raw["hourly"]["temperature_2m"][_row_of(raw, first)]
    assert len(weather.json()["daily"]) == 7
    assert cloud_base.status_code == 200
    assert cloud_base.json()["valid_at"] == _iso(LATEST)
    assert cloud_base.json()["baseline_m"] == expected_baseline_m(raw, LATEST)


# --- OpenAPI ---


def test_openapi_documents_cloud_history(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    operation = schema["paths"]["/cloud-history"]["get"]
    assert {"200", "422", "502"} <= set(operation["responses"])
