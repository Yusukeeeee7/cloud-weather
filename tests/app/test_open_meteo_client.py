import asyncio
import logging
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


# --- #6 リトライ（spec.md「7. 外部API・データ」：リトライは最大 2 回、指数バックオフ） ---

# 最初の 1 回 + リトライ 2 回。
MAX_ATTEMPTS = 3
# 既定の待ち時間（基準 0.5 秒を 2 倍ずつ。2026-10-12 決定）。
DEFAULT_WAITS = [0.5, 1.0]


@pytest.mark.parametrize("error", [httpx.ConnectTimeout, httpx.ReadTimeout])
def test_client_retries_timeout_then_succeeds(
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    waits: list[float],
    error: type[Exception],
) -> None:
    # 受け入れ条件：タイムアウトでリトライ。
    route = open_meteo.get(FORECAST_URL).mock(
        side_effect=[error, httpx.Response(200, json=forecast("tokyo"))]
    )

    result = asyncio.run(_fetch(City.TOKYO))

    assert result == forecast("tokyo")
    assert route.call_count == 2
    assert waits == DEFAULT_WAITS[:1]


def test_client_retries_total_timeout_then_succeeds(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast], waits: list[float]
) -> None:
    # 全体のタイムアウト（httpx の段階ごとのタイムアウトとは別にかけているもの）もリトライする。
    attempts = 0

    async def slow_once(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await asyncio.sleep(5)
        return httpx.Response(200, json=forecast("tokyo"))

    open_meteo.get(FORECAST_URL).mock(side_effect=slow_once)
    # 1 回目は 5 秒かかる。遅い環境でも 2 回目が間に合うよう、余裕のある値にする。
    settings = Settings(_env_file=None, open_meteo_total_timeout_s=1.0)

    result = asyncio.run(_fetch(City.TOKYO, settings))

    assert result == forecast("tokyo")
    assert attempts == 2
    assert waits == DEFAULT_WAITS[:1]


@pytest.mark.parametrize("status", [500, 502, 503])
def test_client_retries_5xx_then_succeeds(
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    waits: list[float],
    status: int,
) -> None:
    # 受け入れ条件：5xx でリトライ。
    route = open_meteo.get(FORECAST_URL).mock(
        side_effect=[httpx.Response(status), httpx.Response(200, json=forecast("tokyo"))]
    )

    result = asyncio.run(_fetch(City.TOKYO))

    assert result == forecast("tokyo")
    assert route.call_count == 2
    assert waits == DEFAULT_WAITS[:1]


@pytest.mark.parametrize("error", [httpx.ReadError, httpx.RemoteProtocolError])
def test_client_retries_dropped_connection_then_succeeds(
    open_meteo: respx.MockRouter,
    forecast: Callable[[str], RawForecast],
    waits: list[float],
    error: type[Exception],
) -> None:
    # 接続が途中で切れた場合も、通信の失敗としてリトライする（2026-10-12 決定）。
    route = open_meteo.get(FORECAST_URL).mock(
        side_effect=[error, httpx.Response(200, json=forecast("tokyo"))]
    )

    result = asyncio.run(_fetch(City.TOKYO))

    assert result == forecast("tokyo")
    assert route.call_count == 2
    assert waits == DEFAULT_WAITS[:1]


@pytest.mark.parametrize("error", [httpx.DecodingError, httpx.TooManyRedirects])
def test_client_does_not_retry_non_transport_errors(
    open_meteo: respx.MockRouter, waits: list[float], error: type[Exception]
) -> None:
    # 通信そのものの失敗ではないもの（圧縮の壊れた応答など）は、壊れた応答と同じくリトライしない。
    route = open_meteo.get(FORECAST_URL).mock(side_effect=error)

    with pytest.raises(UpstreamError):
        asyncio.run(_fetch(City.TOKYO))

    assert route.call_count == 1
    assert waits == []


def test_client_retries_connect_error_then_succeeds(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast], waits: list[float]
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(
        side_effect=[httpx.ConnectError, httpx.Response(200, json=forecast("tokyo"))]
    )

    result = asyncio.run(_fetch(City.TOKYO))

    assert result == forecast("tokyo")
    assert route.call_count == 2
    assert waits == DEFAULT_WAITS[:1]


def test_client_succeeds_on_last_attempt(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast], waits: list[float]
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(
        side_effect=[
            httpx.ReadTimeout,
            httpx.Response(500),
            httpx.Response(200, json=forecast("tokyo")),
        ]
    )

    result = asyncio.run(_fetch(City.TOKYO))

    assert result == forecast("tokyo")
    assert route.call_count == MAX_ATTEMPTS
    assert waits == DEFAULT_WAITS


@pytest.mark.parametrize(
    "upstream",
    [
        {"side_effect": httpx.ConnectTimeout},
        {"side_effect": httpx.ReadTimeout},
        {"side_effect": httpx.ConnectError},
        {"return_value": httpx.Response(500)},
        {"return_value": httpx.Response(503)},
    ],
)
def test_client_gives_up_after_max_retries(
    open_meteo: respx.MockRouter, waits: list[float], upstream: dict[str, object]
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(**upstream)

    with pytest.raises(UpstreamError):
        asyncio.run(_fetch(City.TOKYO))

    # ちょうど 3 回（4 回目はない）。最後の失敗の後は待たない。
    assert route.call_count == MAX_ATTEMPTS
    assert waits == DEFAULT_WAITS


def test_client_backoff_is_exponential(open_meteo: respx.MockRouter, waits: list[float]) -> None:
    # 待ち時間は 基準 × 2^(回数 − 1)。基準と回数は設定の値が使われる（直書きでない）。
    route = open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(500))
    settings = Settings(_env_file=None, open_meteo_max_retries=3, open_meteo_retry_backoff_s=0.25)

    with pytest.raises(UpstreamError):
        asyncio.run(_fetch(City.TOKYO, settings))

    assert route.call_count == 4
    assert waits == [0.25, 0.5, 1.0]


@pytest.mark.parametrize("status", [400, 404, 429])
def test_client_does_not_retry_4xx(
    open_meteo: respx.MockRouter, waits: list[float], status: int
) -> None:
    # 4xx はリトライしない。429（呼びすぎ）も繰り返さない（2026-10-12 決定）。
    route = open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(status))

    with pytest.raises(UpstreamError):
        asyncio.run(_fetch(City.TOKYO))

    assert route.call_count == 1
    assert waits == []


@pytest.mark.parametrize("content", [b"<html>not json</html>", b"", b"[1, 2]"])
def test_client_does_not_retry_invalid_body(
    open_meteo: respx.MockRouter, waits: list[float], content: bytes
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(200, content=content))

    with pytest.raises(UpstreamError):
        asyncio.run(_fetch(City.TOKYO))

    assert route.call_count == 1
    assert waits == []


def test_client_first_success_does_not_wait(
    open_meteo: respx.MockRouter, forecast: Callable[[str], RawForecast], waits: list[float]
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(
        return_value=httpx.Response(200, json=forecast("tokyo"))
    )

    asyncio.run(_fetch(City.TOKYO))

    assert route.call_count == 1
    assert waits == []


@pytest.mark.parametrize(("max_retries", "expected_calls"), [(0, 1), (1, 2)])
def test_client_respects_configured_retries(
    open_meteo: respx.MockRouter, waits: list[float], max_retries: int, expected_calls: int
) -> None:
    route = open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(500))
    settings = Settings(_env_file=None, open_meteo_max_retries=max_retries)

    with pytest.raises(UpstreamError):
        asyncio.run(_fetch(City.TOKYO, settings))

    assert route.call_count == expected_calls
    assert len(waits) == max_retries


@pytest.mark.parametrize(
    "upstream", [{"side_effect": httpx.ConnectError}, {"return_value": httpx.Response(500)}]
)
def test_client_retry_logs_do_not_leak(
    open_meteo: respx.MockRouter,
    caplog: pytest.LogCaptureFixture,
    upstream: dict[str, object],
) -> None:
    open_meteo.get(FORECAST_URL).mock(**upstream)

    with caplog.at_level(logging.WARNING), pytest.raises(UpstreamError):
        asyncio.run(_fetch(City.TOKYO))

    retries = [
        record
        for record in caplog.records
        if record.name == "app.clients.open_meteo" and "retry" in record.getMessage()
    ]
    # リトライのたびに 1 行（2 回）。
    assert len(retries) == 2
    assert all(record.levelno == logging.WARNING for record in retries)
    assert "open-meteo.com" not in caplog.text
    assert "latitude" not in caplog.text
