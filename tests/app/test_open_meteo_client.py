import asyncio
from collections.abc import Callable

import httpx
import pytest
import respx

from app.cities import City
from app.clients.open_meteo import OpenMeteoClient, build_http_client
from app.config import Settings
from app.errors import UpstreamError
from tests.conftest import FORECAST_URL, RawForecast

EXPECTED_CURRENT = (
    "temperature_2m,apparent_temperature,dew_point_2m,relative_humidity_2m,precipitation,"
    "weather_code,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,wind_speed_10m"
)
EXPECTED_HOURLY = (
    "temperature_2m,precipitation_probability,precipitation,weather_code,"
    "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high"
)
EXPECTED_DAILY = (
    "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "precipitation_probability_max,sunrise,sunset"
)
# spec.md「3. 対象地点」の値。
COORDINATES = {City.TOKYO: (35.55, 139.78), City.BERLIN: (52.36, 13.50)}
TIMEZONES = {City.TOKYO: "Asia/Tokyo", City.BERLIN: "Europe/Berlin"}


async def _fetch(city: City, settings: Settings | None = None) -> RawForecast:
    settings = settings or Settings(_env_file=None)
    async with build_http_client(settings) as http:
        return await OpenMeteoClient(http, settings).fetch_forecast(city)


def test_client_requests_expected_host_and_params(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(
        return_value=httpx.Response(200, json=forecast("tokyo"))
    )

    result = asyncio.run(_fetch(City.TOKYO))

    assert route.call_count == 1
    url = route.calls.last.request.url
    assert url.scheme == "https"
    assert url.host == "api.open-meteo.com"
    assert url.path == "/v1/forecast"
    params = dict(url.params)
    assert set(params) == {
        "latitude",
        "longitude",
        "current",
        "hourly",
        "daily",
        "wind_speed_unit",
        "timezone",
        "timeformat",
        "forecast_days",
    }
    assert params["current"] == EXPECTED_CURRENT
    assert params["wind_speed_unit"] == "ms"
    assert result == forecast("tokyo")


def test_client_requests_hourly_and_daily_params(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast]
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(
        return_value=httpx.Response(200, json=forecast("tokyo"))
    )

    asyncio.run(_fetch(City.TOKYO))

    # 現在・時間ごと・日ごとを 1 回の呼び出しでまとめて取得する。
    assert route.call_count == 1
    params = route.calls.last.request.url.params
    assert params["hourly"] == EXPECTED_HOURLY
    assert params["daily"] == EXPECTED_DAILY
    assert params["timeformat"] == "unixtime"
    assert params["forecast_days"] == "7"


@pytest.mark.parametrize("city", [City.TOKYO, City.BERLIN])
def test_client_sends_city_timezone(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast], city: City
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(
        return_value=httpx.Response(200, json=forecast(city.value))
    )

    asyncio.run(_fetch(city))

    assert route.calls.last.request.url.params["timezone"] == TIMEZONES[city]


@pytest.mark.parametrize("city", [City.TOKYO, City.BERLIN])
def test_client_uses_city_coordinates(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast], city: City
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(
        return_value=httpx.Response(200, json=forecast(city.value))
    )

    asyncio.run(_fetch(city))

    params = route.calls.last.request.url.params
    assert (float(params["latitude"]), float(params["longitude"])) == COORDINATES[city]


def test_client_sets_timeout() -> None:
    settings = Settings(_env_file=None)

    http = build_http_client(settings)

    assert http.timeout.connect == 3.0
    assert http.timeout.read == 10.0
    assert http.follow_redirects is False


@pytest.mark.parametrize("error", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError])
def test_client_network_failure_raises_upstream_error(
    open_meteo: respx.MockRouter, error: type[Exception]
) -> None:
    open_meteo.get(FORECAST_URL).mock(side_effect=error)

    with pytest.raises(UpstreamError):
        asyncio.run(_fetch(City.TOKYO))


def test_client_total_timeout_raises_upstream_error(open_meteo: respx.MockRouter) -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json={})

    open_meteo.get(FORECAST_URL).mock(side_effect=slow)
    settings = Settings(_env_file=None, open_meteo_total_timeout_s=0.05)

    with pytest.raises(UpstreamError):
        asyncio.run(_fetch(City.TOKYO, settings))


@pytest.mark.parametrize("status", [500, 503])
def test_client_5xx_raises_upstream_error(open_meteo: respx.MockRouter, status: int) -> None:
    open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(status))

    with pytest.raises(UpstreamError):
        asyncio.run(_fetch(City.TOKYO))


def test_client_400_error_body_raises_upstream_error(open_meteo: respx.MockRouter) -> None:
    # 形式（HTTP 400、error と reason）は公式ドキュメントの記載。reason の文面はテスト用。
    body = {"error": True, "reason": "test reason"}
    open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(400, json=body))

    with pytest.raises(UpstreamError):
        asyncio.run(_fetch(City.TOKYO))


@pytest.mark.parametrize("content", [b"<html>not json</html>", b"", b"[1, 2]"])
def test_client_invalid_json_raises_upstream_error(
    open_meteo: respx.MockRouter, content: bytes
) -> None:
    open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(200, content=content))

    with pytest.raises(UpstreamError):
        asyncio.run(_fetch(City.TOKYO))
