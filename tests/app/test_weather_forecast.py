from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from app.cities import City
from app.errors import UpstreamError
from app.services.weather import build_weather_response
from tests.conftest import FIXED_NOW, RawForecast

Forecast = Callable[[str], RawForecast]

HOURLY_FIELDS = [
    "time",
    "temperature_2m",
    "precipitation_probability",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
]
DAILY_FIELDS = [
    "time",
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "sunrise",
    "sunset",
]
TIMEZONES = {"tokyo": "Asia/Tokyo", "berlin": "Europe/Berlin"}
HOUR = timedelta(hours=1)
# 境界のテストで「現在」に使う hourly の行（先頭でも末尾でもない位置）。
ANCHOR = 30


def _instant(unix_seconds: int) -> datetime:
    return datetime.fromtimestamp(unix_seconds, UTC)


def _first_index(raw: RawForecast, now: datetime) -> int:
    return next(i for i, t in enumerate(raw["hourly"]["time"]) if _instant(t) >= now)


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_fixture_contract_hourly_daily(
    forecast: Forecast, forecast_iso8601: Forecast, city: str
) -> None:
    # 契約の確認：保存した実レスポンスが、前提にしている形・単位になっている。
    raw = forecast(city)
    assert raw["timezone"] == TIMEZONES[city]
    assert raw["hourly_units"]["time"] == "unixtime"
    assert raw["daily_units"]["time"] == "unixtime"
    assert raw["daily_units"]["sunrise"] == "unixtime"
    assert raw["daily_units"]["sunset"] == "unixtime"
    assert raw["hourly_units"]["temperature_2m"] == "°C"
    assert raw["hourly_units"]["precipitation"] == "mm"
    assert raw["hourly_units"]["precipitation_probability"] == "%"
    assert raw["daily_units"]["temperature_2m_max"] == "°C"
    assert raw["daily_units"]["precipitation_sum"] == "mm"
    assert set(raw["hourly"]) == set(HOURLY_FIELDS)
    assert set(raw["daily"]) == set(DAILY_FIELDS)
    assert {len(column) for column in raw["hourly"].values()} == {len(raw["hourly"]["time"])}
    assert {len(column) for column in raw["daily"].values()} == {7}

    reference = forecast_iso8601(city)
    assert reference["timezone"] == TIMEZONES[city]
    assert reference["daily_units"]["time"] == "iso8601"
    assert len(reference["daily"]["time"]) == 7


def test_service_hourly_has_24_items(forecast: Forecast) -> None:
    for city in (City.TOKYO, City.BERLIN):
        response = build_weather_response(city, forecast(city.value), FIXED_NOW)

        assert len(response.hourly) == 24


@pytest.mark.parametrize(
    ("offset_s", "expected_shift"),
    [(0, 0), (-1, 0), (1, 1), (-3599, 0), (3599, 1)],
)
def test_service_hourly_starts_at_or_after_now(
    forecast: Forecast, offset_s: int, expected_shift: int
) -> None:
    # 現在が正時ちょうどならその時刻から、1 秒でも過ぎていれば次の正時から始まる。
    raw = forecast("tokyo")
    anchor = _instant(raw["hourly"]["time"][ANCHOR])

    response = build_weather_response(City.TOKYO, raw, anchor + timedelta(seconds=offset_s))

    assert response.hourly[0].time == _instant(raw["hourly"]["time"][ANCHOR + expected_shift])


def test_service_hourly_is_consecutive_and_utc(forecast: Forecast) -> None:
    response = build_weather_response(City.BERLIN, forecast("berlin"), FIXED_NOW)

    times = [item.time for item in response.hourly]
    assert times[0] >= FIXED_NOW
    assert times[0] - FIXED_NOW < HOUR
    assert [later - earlier for earlier, later in zip(times, times[1:], strict=False)] == [
        HOUR
    ] * 23
    assert all(time.utcoffset() == timedelta(0) for time in times)


@pytest.mark.parametrize("city", [City.TOKYO, City.BERLIN])
def test_service_hourly_maps_fixture_values(forecast: Forecast, city: City) -> None:
    raw = forecast(city.value)
    source = raw["hourly"]
    first = _first_index(raw, FIXED_NOW)

    response = build_weather_response(city, raw, FIXED_NOW)

    for offset, item in enumerate(response.hourly):
        row = first + offset
        assert item.time == _instant(source["time"][row])
        assert item.weather_code == source["weather_code"][row]
        assert item.temperature_c == source["temperature_2m"][row]
        assert item.precipitation_probability == source["precipitation_probability"][row]
        assert item.precipitation_mm == source["precipitation"][row]
        assert item.cloud_cover.total == source["cloud_cover"][row]
        assert item.cloud_cover.low == source["cloud_cover_low"][row]
        assert item.cloud_cover.mid == source["cloud_cover_mid"][row]
        assert item.cloud_cover.high == source["cloud_cover_high"][row]


def test_service_hourly_crosses_local_midnight(forecast: Forecast) -> None:
    # daily の 2 行目の time は、現地の翌日 0 時（Open-Meteo の値）。その 30 分前を現在にする。
    raw = forecast("berlin")
    next_local_midnight = _instant(raw["daily"]["time"][1])

    response = build_weather_response(City.BERLIN, raw, next_local_midnight - timedelta(minutes=30))

    assert len(response.hourly) == 24
    assert response.hourly[0].time == next_local_midnight
    assert response.hourly[-1].time == next_local_midnight + 23 * HOUR


def test_service_hourly_too_few_rows_raises_upstream_error(forecast: Forecast) -> None:
    # 現在以降が 23 件しか残らないように、すべての列を同じ長さに切り詰める。
    raw = forecast("tokyo")
    keep = _first_index(raw, FIXED_NOW) + 23
    raw["hourly"] = {field: column[:keep] for field, column in raw["hourly"].items()}

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


def test_service_hourly_exactly_24_rows_left_is_ok(forecast: Forecast) -> None:
    raw = forecast("tokyo")
    keep = _first_index(raw, FIXED_NOW) + 24
    raw["hourly"] = {field: column[:keep] for field, column in raw["hourly"].items()}

    response = build_weather_response(City.TOKYO, raw, FIXED_NOW)

    assert len(response.hourly) == 24


def test_service_daily_has_7_consecutive_dates(forecast: Forecast) -> None:
    for city in (City.TOKYO, City.BERLIN):
        response = build_weather_response(city, forecast(city.value), FIXED_NOW)

        dates = [item.date for item in response.daily]
        assert len(dates) == 7
        assert [later - earlier for earlier, later in zip(dates, dates[1:], strict=False)] == [
            timedelta(days=1)
        ] * 6


@pytest.mark.parametrize("city", [City.TOKYO, City.BERLIN])
def test_service_daily_dates_match_open_meteo_local_dates(
    forecast: Forecast, forecast_iso8601: Forecast, city: City
) -> None:
    # 期待値は、同じ時刻に iso8601 形式で取得した応答の日付（Open-Meteo が現地の日付で区切った値）。
    expected = forecast_iso8601(city.value)["daily"]["time"]

    response = build_weather_response(city, forecast(city.value), FIXED_NOW)

    assert [item.date.isoformat() for item in response.daily] == expected


def test_service_daily_first_date_is_local_today_not_utc_today(
    forecast: Forecast, forecast_iso8601: Forecast
) -> None:
    # fixture は、東京の日付が UTC の日付より 1 日進んでいる時刻（UTC 15 時台）に取得している。
    local_today = forecast_iso8601("tokyo")["daily"]["time"][0]
    utc_today = FIXED_NOW.date().isoformat()
    assert local_today != utc_today

    response = build_weather_response(City.TOKYO, forecast("tokyo"), FIXED_NOW)

    assert response.daily[0].date.isoformat() == local_today
    assert response.daily[0].date.isoformat() != utc_today


@pytest.mark.parametrize("city", [City.TOKYO, City.BERLIN])
def test_service_daily_maps_fixture_values(forecast: Forecast, city: City) -> None:
    raw = forecast(city.value)
    source = raw["daily"]

    response = build_weather_response(city, raw, FIXED_NOW)

    for row, item in enumerate(response.daily):
        assert item.weather_code == source["weather_code"][row]
        assert item.temperature_max_c == source["temperature_2m_max"][row]
        assert item.temperature_min_c == source["temperature_2m_min"][row]
        assert item.precipitation_probability_max == source["precipitation_probability_max"][row]
        assert item.precipitation_sum_mm == source["precipitation_sum"][row]


@pytest.mark.parametrize("city", [City.TOKYO, City.BERLIN])
def test_service_daily_sunrise_sunset_are_utc(forecast: Forecast, city: City) -> None:
    raw = forecast(city.value)

    response = build_weather_response(city, raw, FIXED_NOW)

    for row, item in enumerate(response.daily):
        assert item.sunrise == _instant(raw["daily"]["sunrise"][row])
        assert item.sunset == _instant(raw["daily"]["sunset"][row])
        assert item.sunrise.utcoffset() == timedelta(0)
        assert item.sunset.utcoffset() == timedelta(0)
        assert item.sunrise < item.sunset


def test_service_daily_sunrise_can_fall_on_previous_utc_date(forecast: Forecast) -> None:
    # 東京の日の出は、UTC では現地の日付の前日になる（spec の例と同じ関係）。
    response = build_weather_response(City.TOKYO, forecast("tokyo"), FIXED_NOW)

    for item in response.daily:
        assert item.sunrise.date() == item.date - timedelta(days=1)


@pytest.mark.parametrize("rows", [0, 6, 8])
def test_service_daily_wrong_row_count_raises_upstream_error(forecast: Forecast, rows: int) -> None:
    # 7 日分を要求しているので、7 行でない応答は受け付けない。
    raw = forecast("tokyo")
    raw["daily"] = {field: (column + column[-1:])[:rows] for field, column in raw["daily"].items()}

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize("field", HOURLY_FIELDS)
def test_service_hourly_missing_field_raises_upstream_error(forecast: Forecast, field: str) -> None:
    raw = forecast("tokyo")
    del raw["hourly"][field]

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize("field", HOURLY_FIELDS)
@pytest.mark.parametrize("position", [0, 23])
def test_service_hourly_null_in_returned_rows_raises_upstream_error(
    forecast: Forecast, field: str, position: int
) -> None:
    raw = forecast("tokyo")
    raw["hourly"][field][_first_index(raw, FIXED_NOW) + position] = None

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize("field", [f for f in HOURLY_FIELDS if f != "time"])
def test_service_hourly_null_outside_returned_rows_is_ignored(
    forecast: Forecast, field: str
) -> None:
    # 返さない範囲（25 件目以降）の null は無視する（先の時刻は値がないことがあるため）。
    raw = forecast("tokyo")
    raw["hourly"][field][_first_index(raw, FIXED_NOW) + 24] = None
    raw["hourly"][field][-1] = None

    response = build_weather_response(City.TOKYO, raw, FIXED_NOW)

    assert len(response.hourly) == 24


@pytest.mark.parametrize("field", DAILY_FIELDS)
def test_service_daily_missing_field_raises_upstream_error(forecast: Forecast, field: str) -> None:
    raw = forecast("tokyo")
    del raw["daily"][field]

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize("field", DAILY_FIELDS)
@pytest.mark.parametrize("row", [0, 6])
def test_service_daily_null_raises_upstream_error(forecast: Forecast, field: str, row: int) -> None:
    raw = forecast("tokyo")
    raw["daily"][field][row] = None

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize("section", ["hourly", "daily"])
def test_service_column_length_mismatch_raises_upstream_error(
    forecast: Forecast, section: str
) -> None:
    # ある列だけ短いと行がずれるので、ずれた行を組み合わせて返さない。
    raw = forecast("tokyo")
    raw[section]["weather_code"].pop()

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


def test_service_hourly_too_many_rows_raises_upstream_error(forecast: Forecast) -> None:
    # Open-Meteo の予報は最大 16 日（384 時間）。それを超える配列は処理しない。
    raw = forecast("tokyo")
    extra = 385 - len(raw["hourly"]["time"])
    last = raw["hourly"]["time"][-1]
    for field, column in raw["hourly"].items():
        if field == "time":
            column.extend(last + 3600 * (i + 1) for i in range(extra))
        else:
            column.extend(column[-1:] * extra)

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize("section", ["hourly", "daily"])
@pytest.mark.parametrize("broken", [None, [], "x", {}, {"time": "x"}])
def test_service_broken_section_raises_upstream_error(
    forecast: Forecast, section: str, broken: object
) -> None:
    raw = forecast("tokyo")
    raw[section] = broken

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize("section", ["hourly", "daily"])
def test_service_section_absent_raises_upstream_error(forecast: Forecast, section: str) -> None:
    raw = forecast("tokyo")
    del raw[section]

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature_2m", "19.3"),
        ("temperature_2m", True),
        ("precipitation_probability", "20"),
        ("precipitation_probability", 20.5),
        ("cloud_cover", 4.5),
        ("weather_code", "0"),
        ("time", "2026-10-13T00:00"),
        ("time", True),
    ],
)
def test_service_hourly_loosely_typed_value_raises_upstream_error(
    forecast: Forecast, field: str, value: object
) -> None:
    raw = forecast("tokyo")
    raw["hourly"][field][_first_index(raw, FIXED_NOW)] = value

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature_2m_max", "24.8"),
        ("temperature_2m_min", True),
        ("precipitation_probability_max", 40.5),
        ("precipitation_sum", "0.5"),
        ("weather_code", "1"),
        ("time", "2026-10-13"),
        ("sunrise", "2026-10-13T05:45"),
        ("sunset", True),
    ],
)
def test_service_daily_loosely_typed_value_raises_upstream_error(
    forecast: Forecast, field: str, value: object
) -> None:
    raw = forecast("tokyo")
    raw["daily"][field][0] = value

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


def test_service_hourly_daily_unknown_weather_code(forecast: Forecast) -> None:
    raw = forecast("tokyo")
    raw["hourly"]["weather_code"][_first_index(raw, FIXED_NOW)] = 1234
    raw["daily"]["weather_code"][0] = 4321

    response = build_weather_response(City.TOKYO, raw, FIXED_NOW)

    assert response.hourly[0].weather == "unknown"
    assert response.hourly[0].weather_code == 1234
    assert response.daily[0].weather == "unknown"
    assert response.daily[0].weather_code == 4321


def test_service_accepts_integer_for_decimal_forecast_field(forecast: Forecast) -> None:
    # JSON では 19.0 が 19 と書かれることがあるため、小数の項目に整数が来ても受け付ける。
    raw = forecast("tokyo")
    raw["hourly"]["temperature_2m"][_first_index(raw, FIXED_NOW)] = 19
    raw["daily"]["precipitation_sum"][0] = 0

    response = build_weather_response(City.TOKYO, raw, FIXED_NOW)

    assert response.hourly[0].temperature_c == 19.0
    assert response.daily[0].precipitation_sum_mm == 0.0


@pytest.mark.parametrize("shift_s", [-3600, 3600])
def test_service_daily_date_survives_one_hour_shift(
    forecast: Forecast, forecast_iso8601: Forecast, shift_s: int
) -> None:
    # 余裕の確認：daily.time が 0 時の瞬間から 1 時間ずれていても、日付が変わらないこと。
    # 実レスポンスでは、夏時間の切り替えをまたいでもこのずれは起きなかった（2026-10-12 に確認）。
    raw = forecast("berlin")
    raw["daily"]["time"] = [value + shift_s for value in raw["daily"]["time"]]

    response = build_weather_response(City.BERLIN, raw, FIXED_NOW)

    expected = forecast_iso8601("berlin")["daily"]["time"]
    assert [item.date.isoformat() for item in response.daily] == expected


@pytest.mark.parametrize("value", [None, "7200", 7200.5, True])
def test_service_broken_utc_offset_raises_upstream_error(forecast: Forecast, value: object) -> None:
    raw = forecast("berlin")
    raw["utc_offset_seconds"] = value

    with pytest.raises(UpstreamError):
        build_weather_response(City.BERLIN, raw, FIXED_NOW)


def test_service_hourly_non_consecutive_times_raise_upstream_error(forecast: Forecast) -> None:
    # 返す 24 件の時刻が 1 時間おきでない応答は受け付けない。
    raw = forecast("tokyo")
    raw["hourly"]["time"][_first_index(raw, FIXED_NOW) + 5] += 60

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


def test_service_daily_non_consecutive_dates_raise_upstream_error(forecast: Forecast) -> None:
    # 7 件の日付が 1 日ずつ進んでいない応答は受け付けない。
    raw = forecast("tokyo")
    raw["daily"]["time"][3] += 86400

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)


@pytest.mark.parametrize(
    ("section", "field"),
    [("current", "time"), ("daily", "time"), ("daily", "sunrise"), ("daily", "sunset")],
)
def test_service_out_of_range_unix_time_raises_upstream_error(
    forecast: Forecast, section: str, field: str
) -> None:
    # 日時に直せないほど大きい UNIX 秒は、例外をそのまま出さず 502 相当にする。
    raw = forecast("tokyo")
    if section == "current":
        raw["current"][field] = 10**20
    else:
        raw["daily"][field][0] = 10**20

    with pytest.raises(UpstreamError):
        build_weather_response(City.TOKYO, raw, FIXED_NOW)
