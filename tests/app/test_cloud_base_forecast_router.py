"""#15 24 時間の予報の雲底：`GET /cloud-base/forecast`（外部APIは respx でモックする）。"""

import copy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.services.cloud_base import MODEL_PATH
from ml import model
from tests.app.cloud_base_fakes import CAP_M, expected_baseline_m, fake_model, training_features
from tests.conftest import (
    FORECAST_URL,
    PAST_NOW,
    FakeClock,
    RawForecast,
    load_past_forecast,
)

RESPONSE_KEYS = {"city", "model_version", "hourly"}
HOUR_KEYS = {"time", "predicted_m", "baseline_m"}
# PAST_NOW（2026-10-14T09:18Z）より後の最初の正時。
FIRST = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
SIX_HOURS = timedelta(hours=6)
# /cloud-base の特徴量に使う 4 項目（#12 で足したもの）。
CLOUD_BASE_ITEMS = ("dew_point_2m", "relative_humidity_2m", "pressure_msl", "wind_speed_10m")


def _iso(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mock_ok(open_meteo: respx.MockRouter, raw: RawForecast) -> respx.Route:
    return open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=raw))


def _use_model(replacement: model.CloudBaseModel | None) -> None:
    from app.main import app
    from app.routers.cloud_base import get_cloud_base_model

    app.dependency_overrides[get_cloud_base_model] = lambda: replacement


def _assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


def _without_cloud_base_items(raw: RawForecast) -> RawForecast:
    """#12 より前の形（4 項目のない hourly）。"""
    changed = copy.deepcopy(raw)
    for item in CLOUD_BASE_ITEMS:
        del changed["hourly"][item]
        del changed["hourly_units"][item]
    return changed


@pytest.fixture
def clock(client: TestClient) -> FakeClock:
    from app.main import app
    from app.routers.weather import get_clock

    fake = FakeClock(PAST_NOW)
    app.dependency_overrides[get_clock] = lambda: fake
    return fake


# --- 正常な応答 ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_forecast_returns_spec_keys_with_committed_model(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    # リポジトリのモデル（起動のときに読み込んだもの）で返す。何 m かの期待値は作らない。
    from app.cities import City

    raw = load_past_forecast(city)
    _mock_ok(open_meteo, raw)
    committed = model.load(MODEL_PATH)

    response = client.get("/cloud-base/forecast", params={"city": city})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESPONSE_KEYS
    assert body["city"] == city
    assert body["model_version"] == committed.model_version
    assert len(body["hourly"]) == 24
    for n, hour in enumerate(body["hourly"]):
        at = FIRST + timedelta(hours=n)
        assert set(hour) == HOUR_KEYS
        assert hour["time"] == _iso(at)
        direct = model.predict_m(committed, training_features(City(city), raw, at)).iloc[0]
        assert hour["predicted_m"] == int(direct + 0.5)
        assert 0 <= hour["predicted_m"] <= CAP_M
        assert hour["baseline_m"] == expected_baseline_m(raw, at)


def test_forecast_times_match_weather(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    _mock_ok(open_meteo, load_past_forecast("tokyo"))
    fake, _ = fake_model(850.0)
    _use_model(fake)

    weather = client.get("/weather", params={"city": "tokyo"})
    forecast = client.get("/cloud-base/forecast", params={"city": "tokyo"})

    weather_times = [hour["time"] for hour in weather.json()["hourly"]]
    assert [hour["time"] for hour in forecast.json()["hourly"]] == weather_times


def test_forecast_city_default_is_tokyo(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    route = _mock_ok(open_meteo, load_past_forecast("tokyo"))
    fake, _ = fake_model(850.0)
    _use_model(fake)

    response = client.get("/cloud-base/forecast")

    assert response.status_code == 200
    assert response.json()["city"] == "tokyo"
    assert route.calls.last.request.url.params["timezone"] == "Asia/Tokyo"


# --- F9・F10：モデルなし、不正な city ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_forecast_model_unavailable_is_503(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    route = _mock_ok(open_meteo, load_past_forecast(city))
    _use_model(None)

    response = client.get("/cloud-base/forecast", params={"city": city})

    _assert_error(response, 503, "model_unavailable")
    assert route.call_count == 0


def test_forecast_invalid_city_wins_over_model_unavailable(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    route = _mock_ok(open_meteo, load_past_forecast("tokyo"))
    _use_model(None)

    response = client.get("/cloud-base/forecast", params={"city": "osaka"})

    _assert_error(response, 422, "invalid_city")
    assert route.call_count == 0


@pytest.mark.parametrize("city", ["", "osaka", "TOKYO", " tokyo", "tokyo,berlin", "../etc"])
def test_forecast_invalid_city(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    route = _mock_ok(open_meteo, load_past_forecast("tokyo"))
    fake, _ = fake_model(850.0)
    _use_model(fake)

    response = client.get("/cloud-base/forecast", params={"city": city})

    _assert_error(response, 422, "invalid_city")
    assert route.call_count == 0


@pytest.mark.parametrize("status", [404, 500])
def test_forecast_upstream_failure_without_cache_is_502(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, status: int
) -> None:
    open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(status))
    fake, _ = fake_model(850.0)
    _use_model(fake)

    response = client.get("/cloud-base/forecast", params={"city": "tokyo"})

    _assert_error(response, 502, "upstream_error")


# --- F11〜F13：キャッシュ ---


@pytest.mark.parametrize(
    "order", [("/weather", "/cloud-base/forecast"), ("/cloud-base/forecast", "/weather")]
)
def test_forecast_shares_cache_with_weather(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, order: tuple[str, str]
) -> None:
    route = _mock_ok(open_meteo, load_past_forecast("tokyo"))
    fake, _ = fake_model(850.0)
    _use_model(fake)

    first = client.get(order[0], params={"city": "tokyo"})
    clock.now = PAST_NOW + timedelta(minutes=14, seconds=59)
    second = client.get(order[1], params={"city": "tokyo"})
    calls_within_ttl = route.call_count
    clock.now = PAST_NOW + timedelta(minutes=15)
    third = client.get("/cloud-base/forecast", params={"city": "tokyo"})

    assert (first.status_code, second.status_code, third.status_code) == (200, 200, 200)
    assert calls_within_ttl == 1
    assert route.call_count == 2


def test_forecast_refetches_when_cached_entry_lacks_items(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    raw = load_past_forecast("tokyo")
    route = _mock_ok(open_meteo, _without_cloud_base_items(raw))
    fake, _ = fake_model(850.0)
    _use_model(fake)
    weather = client.get("/weather", params={"city": "tokyo"})
    assert (weather.status_code, route.call_count) == (200, 1)

    route.mock(return_value=httpx.Response(200, json=raw))
    clock.now = PAST_NOW + timedelta(minutes=5)
    forecast = client.get("/cloud-base/forecast", params={"city": "tokyo"})
    again = client.get("/cloud-base/forecast", params={"city": "tokyo"})

    assert forecast.status_code == 200
    assert forecast.json()["hourly"][0]["baseline_m"] == expected_baseline_m(raw, FIRST)
    # 呼び直した応答は保存され、次は外部APIを呼ばない。
    assert again.json() == forecast.json()
    assert route.call_count == 2


def test_forecast_old_entry_and_upstream_failure_is_502(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    route = _mock_ok(open_meteo, _without_cloud_base_items(load_past_forecast("tokyo")))
    fake, _ = fake_model(850.0)
    _use_model(fake)
    client.get("/weather", params={"city": "tokyo"})

    route.mock(return_value=httpx.Response(500))
    clock.now = PAST_NOW + timedelta(minutes=5)
    response = client.get("/cloud-base/forecast", params={"city": "tokyo"})

    _assert_error(response, 502, "upstream_error")


def test_forecast_uses_stale_cache(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    raw = load_past_forecast("tokyo")
    route = _mock_ok(open_meteo, raw)
    fake, _ = fake_model(850.0)
    _use_model(fake)
    client.get("/cloud-base/forecast", params={"city": "tokyo"})
    route.mock(return_value=httpx.Response(500))

    clock.now = PAST_NOW + timedelta(hours=2)
    stale = client.get("/cloud-base/forecast", params={"city": "tokyo"})
    # 上限（6 時間）ちょうどは返す。過ぎたら 502。
    clock.now = PAST_NOW + SIX_HOURS
    at_limit = client.get("/cloud-base/forecast", params={"city": "tokyo"})
    clock.now = PAST_NOW + SIX_HOURS + timedelta(seconds=1)
    too_old = client.get("/cloud-base/forecast", params={"city": "tokyo"})

    assert stale.status_code == 200
    # 応答のキーは増やさない。時刻は、いまの時刻で選び直す。
    assert set(stale.json()) == RESPONSE_KEYS
    later = FIRST + timedelta(hours=2)
    assert stale.json()["hourly"][0]["time"] == _iso(later)
    assert stale.json()["hourly"][0]["baseline_m"] == expected_baseline_m(raw, later)
    assert at_limit.status_code == 200
    assert at_limit.json()["hourly"][0]["time"] == _iso(FIRST + SIX_HOURS)
    _assert_error(too_old, 502, "upstream_error")


# --- F15：OpenAPI ---


def test_openapi_documents_cloud_base_forecast(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    operation = schema["paths"]["/cloud-base/forecast"]["get"]
    assert {"200", "422", "502", "503"} <= set(operation["responses"])
    text = str(schema["components"]["schemas"]["CloudBaseForecastResponse"]) + str(
        schema["components"]["schemas"]["CloudBaseForecastHour"]
    )
    assert "1524" in text
    assert "not measured" in text
