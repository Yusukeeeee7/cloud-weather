import re
from collections.abc import Callable

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from tests.conftest import FORECAST_URL, RawForecast

UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
TOP_LEVEL_KEYS = {"city", "timezone", "current", "source", "fetched_at"}
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
    assert body["current"]["time"] == raw["current"]["time"] + ":00Z"
    # conftest で固定した時計（2026-10-12T13:41:02.123456Z）の秒未満を切り捨てた値。
    assert body["fetched_at"] == "2026-10-12T13:41:02Z"


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
