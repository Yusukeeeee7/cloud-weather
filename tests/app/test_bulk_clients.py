import asyncio
import logging

import httpx
import pytest
import respx

from app.cities import CITIES, City
from app.clients.bulk import build_bulk_http_client
from app.clients.iem import IemClient
from app.clients.open_meteo_archive import OpenMeteoArchiveClient
from app.config import Settings
from app.errors import UpstreamError
from tests.ml.refs import archive_text, metar_text

IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# 2026-10-12 に確認して決めた、IEM から取る列。
IEM_COLUMNS = [
    "tmpf",
    "dwpf",
    "vsby",
    "skyc1",
    "skyc2",
    "skyc3",
    "skyc4",
    "skyl1",
    "skyl2",
    "skyl3",
    "skyl4",
    "wxcodes",
    "metar",
]
ARCHIVE_HOURLY = (
    "temperature_2m,dew_point_2m,relative_humidity_2m,pressure_msl,precipitation,weather_code,"
    "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,wind_speed_10m"
)
# spec.md「3. 対象地点」の値。
ICAO = {City.TOKYO: "RJTT", City.BERLIN: "EDDB"}
COORDINATES = {City.TOKYO: (35.55, 139.78), City.BERLIN: (52.36, 13.50)}
SOURCES = ["iem", "archive"]


def _settings(**values: float | int | str) -> Settings:
    return Settings(_env_file=None, **values)


async def _fetch_metar(
    city: City, year: int, settings: Settings | None = None, times: int = 1
) -> str:
    settings = settings or _settings()
    async with build_bulk_http_client(settings.iem_base_url, settings) as http:
        client = IemClient(http, settings)
        for _ in range(times - 1):
            await client.fetch_metar(city, year)
        return await client.fetch_metar(city, year)


async def _fetch_hourly(city: City, year: int, settings: Settings | None = None) -> str:
    settings = settings or _settings()
    async with build_bulk_http_client(settings.open_meteo_archive_base_url, settings) as http:
        return await OpenMeteoArchiveClient(http, settings).fetch_hourly(city, year)


def _url(source: str) -> str:
    return IEM_URL if source == "iem" else ARCHIVE_URL


def _body(source: str) -> str:
    return metar_text("tokyo") if source == "iem" else archive_text("tokyo")


def _fetch(source: str, settings: Settings | None = None) -> str:
    if source == "iem":
        return asyncio.run(_fetch_metar(City.TOKYO, 2025, settings))
    return asyncio.run(_fetch_hourly(City.TOKYO, 2025, settings))


@pytest.mark.parametrize("city", list(City))
def test_iem_client_requests_expected_parameters(open_meteo: respx.MockRouter, city: City) -> None:
    body = metar_text(city.value)
    route = open_meteo.get(IEM_URL).mock(return_value=httpx.Response(200, text=body))

    result = asyncio.run(_fetch_metar(city, 2025))

    assert result == body
    assert route.call_count == 1
    url = route.calls.last.request.url
    assert (url.scheme, url.host, url.path) == (
        "https",
        "mesonet.agron.iastate.edu",
        "/cgi-bin/request/asos.py",
    )
    params = url.params
    assert set(params.keys()) == {
        "station",
        "data",
        "sts",
        "ets",
        "tz",
        "format",
        "missing",
        "trace",
        "report_type",
    }
    assert params.get_list("station") == [ICAO[city]]
    assert params.get_list("data") == IEM_COLUMNS
    # 開始を含み、終了を含まない。1 年ぶん（UTC）。
    assert params["sts"] == "2025-01-01T00:00:00Z"
    assert params["ets"] == "2026-01-01T00:00:00Z"
    assert params["tz"] == "UTC"
    assert params["format"] == "onlycomma"
    assert params["missing"] == "empty"
    assert params["trace"] == "empty"
    # 定時（3）と臨時（4）。
    assert params.get_list("report_type") == ["3", "4"]


@pytest.mark.parametrize("city", list(City))
def test_archive_client_requests_expected_parameters(
    open_meteo: respx.MockRouter, city: City
) -> None:
    body = archive_text(city.value)
    route = open_meteo.get(ARCHIVE_URL).mock(return_value=httpx.Response(200, text=body))

    result = asyncio.run(_fetch_hourly(city, 2018))

    assert result == body
    assert route.call_count == 1
    url = route.calls.last.request.url
    assert (url.scheme, url.host, url.path) == (
        "https",
        "archive-api.open-meteo.com",
        "/v1/archive",
    )
    params = dict(url.params)
    assert set(params) == {
        "latitude",
        "longitude",
        "hourly",
        "start_date",
        "end_date",
        "wind_speed_unit",
        "timeformat",
    }
    assert (float(params["latitude"]), float(params["longitude"])) == COORDINATES[city]
    assert params["hourly"] == ARCHIVE_HOURLY
    assert params["start_date"] == "2018-01-01"
    assert params["end_date"] == "2018-12-31"
    assert params["wind_speed_unit"] == "ms"
    assert params["timeformat"] == "unixtime"


def test_cities_have_icao() -> None:
    assert {city: CITIES[city].icao for city in City} == ICAO


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("city", ["RJTT", "KJFK", "osaka", "", "tokyo,berlin", "../etc"])
def test_clients_take_city_from_allowlist_only(
    open_meteo: respx.MockRouter, source: str, city: str
) -> None:
    route = open_meteo.get(_url(source)).mock(return_value=httpx.Response(200, text=_body(source)))
    fetch = _fetch_metar if source == "iem" else _fetch_hourly

    with pytest.raises(ValueError):
        asyncio.run(fetch(city, 2025))

    assert route.call_count == 0


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("year", [1939, 2101, 0, -2025, 20250])
def test_clients_reject_year_out_of_range(
    open_meteo: respx.MockRouter, source: str, year: int
) -> None:
    route = open_meteo.get(_url(source)).mock(return_value=httpx.Response(200, text=_body(source)))
    fetch = _fetch_metar if source == "iem" else _fetch_hourly

    with pytest.raises(ValueError):
        asyncio.run(fetch(City.TOKYO, year))

    assert route.call_count == 0


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize(
    "failure",
    [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError, 500, 502, 503],
)
def test_clients_retry_timeout_and_5xx_then_succeed(
    open_meteo: respx.MockRouter, waits: list[float], source: str, failure: object
) -> None:
    first = httpx.Response(failure) if isinstance(failure, int) else failure
    route = open_meteo.get(_url(source)).mock(
        side_effect=[first, httpx.Response(200, text=_body(source))]
    )

    result = _fetch(source)

    assert result == _body(source)
    assert route.call_count == 2
    assert waits == [0.5]


@pytest.mark.parametrize("source", SOURCES)
def test_clients_give_up_after_max_retries(
    open_meteo: respx.MockRouter, waits: list[float], source: str
) -> None:
    route = open_meteo.get(_url(source)).mock(return_value=httpx.Response(503))

    with pytest.raises(UpstreamError):
        _fetch(source)

    # 最初の 1 回 + リトライ 2 回。待ち時間は 0.5 秒 → 1.0 秒。
    assert route.call_count == 3
    assert waits == [0.5, 1.0]


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("status", [400, 404, 422, 429])
def test_clients_do_not_retry_4xx(
    open_meteo: respx.MockRouter, waits: list[float], source: str, status: int
) -> None:
    # 429（呼びすぎ）・422（IEM：要求が大きすぎる）も繰り返さない。
    route = open_meteo.get(_url(source)).mock(return_value=httpx.Response(status))

    with pytest.raises(UpstreamError):
        _fetch(source)

    assert route.call_count == 1
    assert waits == []


@pytest.mark.parametrize("source", SOURCES)
def test_clients_respect_configured_retries(open_meteo: respx.MockRouter, source: str) -> None:
    route = open_meteo.get(_url(source)).mock(return_value=httpx.Response(500))

    with pytest.raises(UpstreamError):
        _fetch(source, _settings(open_meteo_max_retries=0))

    assert route.call_count == 1


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("body", ["", "  \n"])
def test_clients_reject_empty_body(open_meteo: respx.MockRouter, source: str, body: str) -> None:
    route = open_meteo.get(_url(source)).mock(return_value=httpx.Response(200, text=body))

    with pytest.raises(UpstreamError):
        _fetch(source)

    assert route.call_count == 1


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "[]",
        '{"error": true, "reason": "Parameter start_date is out of allowed range"}',
        '{"latitude": 35.6}',
    ],
)
def test_archive_client_error_body_raises(open_meteo: respx.MockRouter, body: str) -> None:
    route = open_meteo.get(ARCHIVE_URL).mock(return_value=httpx.Response(200, text=body))

    with pytest.raises(UpstreamError):
        _fetch("archive")

    assert route.call_count == 1


@pytest.mark.parametrize(
    "body", ["<html><body>Too Many Requests</body></html>", "ERROR: station not found\n"]
)
def test_iem_client_non_csv_body_raises(open_meteo: respx.MockRouter, body: str) -> None:
    # 200 でも、1 行目が列名（station,valid,…）でなければ失敗として扱う。
    route = open_meteo.get(IEM_URL).mock(return_value=httpx.Response(200, text=body))

    with pytest.raises(UpstreamError):
        _fetch("iem")

    assert route.call_count == 1


def test_iem_client_waits_between_requests(
    open_meteo: respx.MockRouter, waits: list[float]
) -> None:
    # IEM は同じ IP から 1 秒に 1 回まで。続けて呼ぶときは間をあける（最初の 1 回は待たない）。
    route = open_meteo.get(IEM_URL).mock(return_value=httpx.Response(200, text=metar_text("tokyo")))

    asyncio.run(_fetch_metar(City.TOKYO, 2025, times=3))

    assert route.call_count == 3
    assert waits == [2.0, 2.0]


def test_iem_client_uses_configured_interval(
    open_meteo: respx.MockRouter, waits: list[float]
) -> None:
    open_meteo.get(IEM_URL).mock(return_value=httpx.Response(200, text=metar_text("tokyo")))

    asyncio.run(_fetch_metar(City.TOKYO, 2025, _settings(iem_request_interval_s=5), times=2))

    assert waits == [5.0]


def test_archive_client_does_not_wait_between_requests(
    open_meteo: respx.MockRouter, waits: list[float]
) -> None:
    open_meteo.get(ARCHIVE_URL).mock(return_value=httpx.Response(200, text=archive_text("tokyo")))

    async def twice() -> None:
        settings = _settings()
        async with build_bulk_http_client(settings.open_meteo_archive_base_url, settings) as http:
            client = OpenMeteoArchiveClient(http, settings)
            await client.fetch_hourly(City.TOKYO, 2024)
            await client.fetch_hourly(City.TOKYO, 2025)

    asyncio.run(twice())

    assert waits == []


def test_bulk_http_client_uses_configured_timeouts() -> None:
    default = build_bulk_http_client("https://example.invalid", _settings())
    custom = build_bulk_http_client(
        "https://example.invalid",
        _settings(data_fetch_timeout_s=120, open_meteo_connect_timeout_s=1.5),
    )

    # 一括取得は全体 60 秒（既定）。接続は 3 秒のまま。
    assert default.timeout == httpx.Timeout(60.0, connect=3.0)
    assert custom.timeout == httpx.Timeout(120.0, connect=1.5)
    assert default.follow_redirects is False
    assert str(default.base_url).rstrip("/") == "https://example.invalid"


@pytest.mark.parametrize("source", SOURCES)
def test_clients_enforce_total_timeout(open_meteo: respx.MockRouter, source: str) -> None:
    started: list[httpx.Request] = []

    async def slow(request: httpx.Request) -> httpx.Response:
        started.append(request)
        await asyncio.sleep(1)
        return httpx.Response(200, text=_body(source))

    open_meteo.get(_url(source)).mock(side_effect=slow)

    with pytest.raises(UpstreamError):
        _fetch(source, _settings(data_fetch_timeout_s=0.05, open_meteo_max_retries=0))

    # 途中で打ち切った要求は respx の回数に数えられないので、始まった回数を自分で数える。
    assert len(started) == 1


@pytest.mark.parametrize("source", SOURCES)
def test_clients_use_configured_base_url(open_meteo: respx.MockRouter, source: str) -> None:
    name = "iem_base_url" if source == "iem" else "open_meteo_archive_base_url"
    path = "/cgi-bin/request/asos.py" if source == "iem" else "/v1/archive"
    route = open_meteo.get(f"https://example.invalid{path}").mock(
        return_value=httpx.Response(200, text=_body(source))
    )

    _fetch(source, _settings(**{name: "https://example.invalid"}))

    assert route.call_count == 1


@pytest.mark.parametrize("source", SOURCES)
def test_clients_failure_does_not_leak_url(
    open_meteo: respx.MockRouter, caplog: pytest.LogCaptureFixture, source: str
) -> None:
    open_meteo.get(_url(source)).mock(side_effect=httpx.ConnectError)

    with caplog.at_level(logging.WARNING), pytest.raises(UpstreamError) as error:
        _fetch(source)

    # アプリのログ（app. で始まるロガー）だけを見る。
    messages = [record.getMessage() for record in caplog.records if record.name.startswith("app.")]
    assert messages
    for text in [str(error.value), *messages]:
        assert "http" not in text
        assert "iastate" not in text
        assert "open-meteo.com" not in text
        assert "RJTT" not in text
