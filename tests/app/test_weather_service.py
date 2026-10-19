import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from app.cities import City
from app.errors import UpstreamError
from app.services.weather import build_weather_response
from tests.conftest import FIXED_NOW, RawForecast

REQUIRED_FIELDS = [
    "time",
    "temperature_2m",
    "apparent_temperature",
    "dew_point_2m",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "wind_speed_10m",
    "wind_direction_10m",
]


def test_fixture_matches_requested_units(forecast: Callable[[str], RawForecast]) -> None:
    # 契約の確認：保存した実レスポンスが、前提にしている単位と時刻形式（UNIX 秒）になっている。
    for city in ("tokyo", "berlin"):
        raw = forecast(city)
        assert raw["current_units"]["time"] == "unixtime"
        assert raw["current_units"]["wind_speed_10m"] == "m/s"
        assert raw["current_units"]["temperature_2m"] == "°C"
        assert raw["current_units"]["precipitation"] == "mm"


@pytest.mark.parametrize(
    ("city", "timezone"), [(City.TOKYO, "Asia/Tokyo"), (City.BERLIN, "Europe/Berlin")]
)
def test_service_maps_fixture_to_current(
    forecast: Callable[[str], RawForecast], city: City, timezone: str
) -> None:
    raw = forecast(city.value)
    source = raw["current"]

    response = build_weather_response(city, raw, FIXED_NOW)

    assert response.city == city.value
    assert response.timezone == timezone
    assert response.source == "open-meteo"
    current = response.current
    assert current.weather_code == source["weather_code"]
    assert current.temperature_c == source["temperature_2m"]
    assert current.apparent_temperature_c == source["apparent_temperature"]
    assert current.dew_point_c == source["dew_point_2m"]
    assert current.relative_humidity == source["relative_humidity_2m"]
    assert current.precipitation_mm == source["precipitation"]
    assert current.wind_speed_ms == source["wind_speed_10m"]
    assert current.cloud_cover.total == source["cloud_cover"]
    assert current.cloud_cover.low == source["cloud_cover_low"]
    assert current.cloud_cover.mid == source["cloud_cover_mid"]
    assert current.cloud_cover.high == source["cloud_cover_high"]


def test_service_time_is_utc(forecast: Callable[[str], RawForecast]) -> None:
    raw = forecast("tokyo")

    response = build_weather_response(City.TOKYO, raw, FIXED_NOW)

    expected = datetime.fromtimestamp(raw["current"]["time"], UTC)
    assert response.current.time == expected
    assert response.current.time.utcoffset() == UTC.utcoffset(None)


def test_service_current_time_is_close_to_fetch_time(
    forecast: Callable[[str], RawForecast],
) -> None:
    # タイムゾーンを渡しても current.time が現地時刻として読まれていない（数時間ずれていない）こと。
    # Open-Meteo の current は 15 分間隔（interval 900 秒）に丸めた時刻を返す。
    for city in (City.TOKYO, City.BERLIN):
        response = build_weather_response(city, forecast(city.value), FIXED_NOW)

        assert abs(FIXED_NOW - response.current.time) <= timedelta(minutes=15)


def test_service_fetched_at_drops_sub_seconds(forecast: Callable[[str], RawForecast]) -> None:
    response = build_weather_response(City.TOKYO, forecast("tokyo"), FIXED_NOW)

    assert response.fetched_at == FIXED_NOW.replace(microsecond=0)


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_service_missing_field_raises_upstream_error(
    forecast: Callable[[str], RawForecast], field: str
) -> None:
    raw = forecast("tokyo")
    del raw["current"][field]

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_service_null_field_raises_upstream_error(
    forecast: Callable[[str], RawForecast], field: str
) -> None:
    raw = forecast("tokyo")
    raw["current"][field] = None

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize(
    "field",
    [
        "temperature_2m",
        "apparent_temperature",
        "dew_point_2m",
        "precipitation",
        "wind_speed_10m",
        "wind_direction_10m",
    ],
)
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_service_not_finite_field_raises_upstream_error(
    forecast: Callable[[str], RawForecast], field: str, value: float
) -> None:
    # 小数の項目。受け付けると、応答で null になって 200 で返る（#58 のレビュー）。
    raw = forecast("tokyo")
    raw["current"][field] = value

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize("current", [None, [], "x"])
def test_service_broken_current_raises_upstream_error(
    forecast: Callable[[str], RawForecast], current: object
) -> None:
    raw = forecast("tokyo")
    raw["current"] = current

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


def test_service_wrong_type_raises_upstream_error(forecast: Callable[[str], RawForecast]) -> None:
    raw = forecast("tokyo")
    raw["current"]["temperature_2m"] = "warm"

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


def test_service_invalid_time_raises_upstream_error(forecast: Callable[[str], RawForecast]) -> None:
    raw = forecast("tokyo")
    raw["current"]["time"] = "not-a-time"

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


def test_service_unknown_weather_code(forecast: Callable[[str], RawForecast]) -> None:
    raw = forecast("tokyo")
    raw["current"]["weather_code"] = 1234

    response = build_weather_response(City.TOKYO, raw, FIXED_NOW)

    assert response.current.weather == "unknown"
    assert response.current.weather_code == 1234


def test_service_classifies_fixture_weather_code(forecast: Callable[[str], RawForecast]) -> None:
    # 保存時の東京は weather_code 51（drizzle）、ベルリンは 2（partly_cloudy）。
    # 承認済みの表のとおり。
    expected = {City.TOKYO: "drizzle", City.BERLIN: "partly_cloudy"}
    for city, category in expected.items():
        response = build_weather_response(city, forecast(city.value), FIXED_NOW)
        assert response.current.weather == category


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature_2m", "19.3"),
        ("temperature_2m", True),
        ("relative_humidity_2m", "80"),
        ("relative_humidity_2m", True),
        ("relative_humidity_2m", 80.5),
        ("cloud_cover", 4.5),
        ("weather_code", "0"),
        # 時刻は UNIX 秒（整数）で受け取る。文字列・真偽値・小数は受け付けない。
        ("time", "2026-10-12T13:30"),
        ("time", True),
        ("time", 1791813600.5),
    ],
)
def test_service_loosely_typed_value_raises_upstream_error(
    forecast: Callable[[str], RawForecast], field: str, value: object
) -> None:
    raw = forecast("tokyo")
    raw["current"][field] = value

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


def test_service_accepts_integer_for_decimal_field(forecast: Callable[[str], RawForecast]) -> None:
    # JSON では 19.0 が 19 と書かれることがあるため、小数の項目に整数が来ても受け付ける。
    raw = forecast("tokyo")
    raw["current"]["temperature_2m"] = 19

    response = build_weather_response(City.TOKYO, raw, FIXED_NOW)

    assert response.current.temperature_c == 19.0
