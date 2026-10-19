"""#15 過去 24 時間の雲底：`GET /cloud-base/history`（外部APIは respx でモックする）。"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.cities import City
from app.services.cloud_base import MODEL_PATH
from ml import model
from tests.app.cloud_base_fakes import (
    CAP_M,
    expected_baseline_m,
    fake_model,
    training_features,
    use_model,
)
from tests.conftest import (
    FIXED_NOW,
    FORECAST_URL,
    PAST_NOW,
    FakeClock,
    assert_error,
    iso,
    load_forecast,
    load_past_forecast,
    mock_ok,
    seed_weather_cache,
    without_past_hours,
)

RESPONSE_KEYS = {"city", "model_version", "hourly"}
HOUR_KEYS = {"time", "predicted_m", "baseline_m"}
# PAST_NOW（2026-10-14T09:18Z）以前の最も近い正時と、その 23 時間前。
LATEST = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
FIRST = LATEST - timedelta(hours=23)
SIX_HOURS = timedelta(hours=6)


@pytest.fixture
def clock(client: TestClient) -> FakeClock:
    from app.main import app
    from app.routers.weather import get_clock

    fake = FakeClock(PAST_NOW)
    app.dependency_overrides[get_clock] = lambda: fake
    return fake


# --- 正常な応答 ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_history_returns_spec_keys_with_committed_model(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    # リポジトリのモデルで返す。何 m かの期待値は作らず、ml/ の関数を直接呼んだ値と比べる。
    raw = load_past_forecast(city)
    mock_ok(open_meteo, raw)
    committed = model.load(MODEL_PATH)

    response = client.get("/cloud-base/history", params={"city": city})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESPONSE_KEYS
    assert body["city"] == city
    assert body["model_version"] == committed.model_version
    assert len(body["hourly"]) == 24
    for n, hour in enumerate(body["hourly"]):
        at = FIRST + timedelta(hours=n)
        assert set(hour) == HOUR_KEYS
        assert hour["time"] == iso(at)
        direct = model.predict_m(committed, training_features(City(city), raw, at)).iloc[0]
        assert hour["predicted_m"] == int(direct + 0.5)
        assert 0 <= hour["predicted_m"] <= CAP_M
        assert hour["baseline_m"] == expected_baseline_m(raw, at)


def test_history_times_match_cloud_history(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    mock_ok(open_meteo, load_past_forecast("tokyo"))
    fake, _ = fake_model(850.0)
    use_model(fake)

    cover = client.get("/cloud-history", params={"city": "tokyo"})
    ceiling = client.get("/cloud-base/history", params={"city": "tokyo"})

    cover_times = [hour["time"] for hour in cover.json()["hourly"]]
    assert [hour["time"] for hour in ceiling.json()["hourly"]] == cover_times


def test_history_city_default_is_tokyo(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    route = mock_ok(open_meteo, load_past_forecast("tokyo"))
    fake, _ = fake_model(850.0)
    use_model(fake)

    response = client.get("/cloud-base/history")

    assert response.json()["city"] == "tokyo"
    assert route.calls.last.request.url.params["timezone"] == "Asia/Tokyo"


# --- H7：モデルなし、不正な city ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_history_model_unavailable_is_503(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    route = mock_ok(open_meteo, load_past_forecast(city))
    use_model(None)

    response = client.get("/cloud-base/history", params={"city": city})

    assert_error(response, 503, "model_unavailable")
    assert route.call_count == 0


def test_history_invalid_city_wins_over_model_unavailable(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    route = mock_ok(open_meteo, load_past_forecast("tokyo"))
    use_model(None)

    response = client.get("/cloud-base/history", params={"city": "osaka"})

    assert_error(response, 422, "invalid_city")
    assert route.call_count == 0


@pytest.mark.parametrize("city", ["", "osaka", "TOKYO", " tokyo", "tokyo,berlin", "../etc"])
def test_history_invalid_city(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    route = mock_ok(open_meteo, load_past_forecast("tokyo"))
    fake, _ = fake_model(850.0)
    use_model(fake)

    response = client.get("/cloud-base/history", params={"city": city})

    assert_error(response, 422, "invalid_city")
    assert route.call_count == 0


@pytest.mark.parametrize("status", [404, 500])
def test_history_upstream_failure_without_cache_is_502(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, status: int
) -> None:
    open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(status))
    fake, _ = fake_model(850.0)
    use_model(fake)

    response = client.get("/cloud-base/history", params={"city": "tokyo"})

    assert_error(response, 502, "upstream_error")


# --- H6・H8：キャッシュ ---


@pytest.mark.parametrize("first_path", ["/weather", "/cloud-history"])
def test_history_shares_cache(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, first_path: str
) -> None:
    # /weather は風向が要る（#58）ので、風向のある fixture とその取得時刻を使う。
    route = mock_ok(open_meteo, load_forecast("tokyo"))
    clock.now = FIXED_NOW
    fake, _ = fake_model(850.0)
    use_model(fake)

    first = client.get(first_path, params={"city": "tokyo"})
    clock.now = FIXED_NOW + timedelta(minutes=14, seconds=59)
    hit = client.get("/cloud-base/history", params={"city": "tokyo"})
    calls_within_ttl = route.call_count
    clock.now = FIXED_NOW + timedelta(minutes=15)
    miss = client.get("/cloud-base/history", params={"city": "tokyo"})

    assert (first.status_code, hit.status_code, miss.status_code) == (200, 200, 200)
    assert calls_within_ttl == 1
    assert route.call_count == 2


def test_history_refetches_when_cached_value_lacks_past_hours(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    # 過去の時間のない保存値は、/weather を通さずに保存先に入れる（/weather は風向が要る。#58）。
    raw = load_past_forecast("tokyo")
    seed_weather_cache(client, "tokyo", without_past_hours(raw), PAST_NOW)
    route = mock_ok(open_meteo, raw)
    fake, _ = fake_model(850.0)
    use_model(fake)

    clock.now = PAST_NOW + timedelta(minutes=5)
    history = client.get("/cloud-base/history", params={"city": "tokyo"})
    again = client.get("/cloud-base/history", params={"city": "tokyo"})

    assert history.status_code == 200
    assert history.json()["hourly"][0]["time"] == iso(FIRST)
    assert again.json() == history.json()
    # TTL の内の保存値を使わずに 1 回だけ呼び直し、その応答を保存する。
    assert route.call_count == 1


def test_history_old_value_and_upstream_failure_is_502(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    seed_weather_cache(client, "tokyo", without_past_hours(load_past_forecast("tokyo")), PAST_NOW)
    open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(500))
    fake, _ = fake_model(850.0)
    use_model(fake)

    clock.now = PAST_NOW + timedelta(minutes=5)
    response = client.get("/cloud-base/history", params={"city": "tokyo"})

    assert_error(response, 502, "upstream_error")


def test_history_uses_stale_cache(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    raw = load_past_forecast("tokyo")
    route = mock_ok(open_meteo, raw)
    fake, _ = fake_model(850.0)
    use_model(fake)
    client.get("/cloud-base/history", params={"city": "tokyo"})
    route.mock(return_value=httpx.Response(500))

    clock.now = PAST_NOW + timedelta(hours=2)
    stale = client.get("/cloud-base/history", params={"city": "tokyo"})
    clock.now = PAST_NOW + SIX_HOURS
    at_limit = client.get("/cloud-base/history", params={"city": "tokyo"})
    clock.now = PAST_NOW + SIX_HOURS + timedelta(seconds=1)
    too_old = client.get("/cloud-base/history", params={"city": "tokyo"})

    assert stale.status_code == 200
    assert set(stale.json()) == RESPONSE_KEYS
    later = LATEST + timedelta(hours=2)
    assert stale.json()["hourly"][-1]["time"] == iso(later)
    assert stale.json()["hourly"][-1]["baseline_m"] == expected_baseline_m(raw, later)
    assert at_limit.status_code == 200
    assert at_limit.json()["hourly"][-1]["time"] == iso(LATEST + SIX_HOURS)
    assert_error(too_old, 502, "upstream_error")


# --- H10：OpenAPI ---


def test_openapi_documents_cloud_base_history(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    operation = schema["paths"]["/cloud-base/history"]["get"]
    assert {"200", "422", "502", "503"} <= set(operation["responses"])
    text = str(schema["components"]["schemas"]["CloudBaseHistoryResponse"]) + str(
        schema["components"]["schemas"]["CloudBaseForecastHour"]
    )
    assert "1524" in text
    assert "not observations" in text
