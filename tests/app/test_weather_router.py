import re
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from tests.conftest import FORECAST_URL, RawForecast

UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
LOCAL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TOP_LEVEL_KEYS = {"city", "timezone", "current", "hourly", "daily", "source", "fetched_at"}
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
    assert "cached" not in body
    assert "stale" not in body
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
