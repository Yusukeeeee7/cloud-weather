from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services import solar
from tests.solar_refs import (
    TOLERANCE,
    NoaaSheet,
    coordinates,
    open_meteo_sun_times,
    usno_transit,
    usno_twilight,
)

# spec.md「用語の定義」の太陽の高度。
SUNRISE_ALTITUDE = -0.833
TWILIGHT_ALTITUDES = {"civil": -6.0, "nautical": -12.0, "astronomical": -18.0}
REFERENCE_DAYS = [date(2026, 3, 20), date(2026, 6, 21), date(2026, 12, 21)]
BERLIN = ZoneInfo("Europe/Berlin")


def _assert_close(actual: datetime | None, expected: datetime) -> None:
    assert actual is not None
    assert abs(actual - expected) <= TOLERANCE, f"{actual} vs {expected}"


def _assert_sun_times_match(city: str, fixture: str, days: list[date] | None = None) -> None:
    latitude, longitude = coordinates(city)
    expected = open_meteo_sun_times(fixture, city)
    for day in days if days is not None else sorted(expected):
        sunrise, sunset = expected[day]
        crossing = solar.altitude_crossing(latitude, longitude, day, SUNRISE_ALTITUDE)
        _assert_close(crossing.morning, sunrise)
        _assert_close(crossing.evening, sunset)


# --- NOAA のスプレッドシートの値（式そのものの確認） ---


def test_declination_matches_noaa_sheet() -> None:
    sheet = NoaaSheet()

    for row in sheet.rows:
        actual = solar.solar_declination_deg(sheet.row_time(row))
        assert actual == pytest.approx(row["Sun Declin (deg)"], abs=1e-6)


def test_equation_of_time_matches_noaa_sheet() -> None:
    sheet = NoaaSheet()

    for row in sheet.rows:
        actual = solar.equation_of_time_min(sheet.row_time(row))
        assert actual == pytest.approx(row["Eq of Time (minutes)"], abs=1e-6)


def test_elevation_matches_noaa_sheet() -> None:
    # 大気差の補正を入れない高度（表の「Solar Elevation Angle」）。
    sheet = NoaaSheet()

    for row in sheet.rows:
        actual = solar.solar_elevation_deg(sheet.latitude, sheet.longitude, sheet.row_time(row))
        assert actual == pytest.approx(row["Solar Elevation Angle (deg)"], abs=1e-6)


def test_noon_sunrise_sunset_match_noaa_sheet() -> None:
    sheet = NoaaSheet()
    one_second = timedelta(seconds=1)

    noon = solar.solar_noon(sheet.longitude, sheet.day)
    crossing = solar.altitude_crossing(sheet.latitude, sheet.longitude, sheet.day, SUNRISE_ALTITUDE)

    assert abs(noon - sheet.event_time("Solar Noon (LST)")) <= one_second
    assert crossing.morning is not None and crossing.evening is not None
    assert abs(crossing.morning - sheet.event_time("Sunrise Time (LST)")) <= one_second
    assert abs(crossing.evening - sheet.event_time("Sunset Time (LST)")) <= one_second


# --- Open-Meteo の日の出・日の入り（受け入れ条件：±2 分以内） ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_sunrise_sunset_match_open_meteo_within_2_minutes(city: str) -> None:
    expected = open_meteo_sun_times(f"forecast_{city}.json", city)
    assert len(expected) == 7

    _assert_sun_times_match(city, f"forecast_{city}.json")


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_sunrise_sunset_match_open_meteo_for_16_days(city: str) -> None:
    expected = open_meteo_sun_times(f"sun_{city}_16days.json", city)
    assert len(expected) == 16

    _assert_sun_times_match(city, f"sun_{city}_16days.json")


def test_sunrise_sunset_on_dst_change_day() -> None:
    # ベルリンの夏時間が終わる日（2026-10-25）とその前後、始まる日（2026-03-29）とその前後。
    end, start = date(2026, 10, 25), date(2026, 3, 29)
    for change in (end, start):
        before = datetime(change.year, change.month, change.day - 1, 12, tzinfo=BERLIN)
        after = datetime(change.year, change.month, change.day, 12, tzinfo=BERLIN)
        assert before.utcoffset() != after.utcoffset()

    one_day = timedelta(days=1)
    _assert_sun_times_match("berlin", "sun_berlin_16days.json", [end - one_day, end, end + one_day])
    _assert_sun_times_match(
        "berlin", "archive_sun_berlin.json", [start - one_day, start, start + one_day]
    )


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
@pytest.mark.parametrize("day", [date(2025, 12, 21), date(2026, 3, 20), date(2026, 6, 21)])
def test_sunrise_sunset_on_solstices_and_equinox(city: str, day: date) -> None:
    _assert_sun_times_match(city, f"archive_sun_{city}.json", [day])


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_sunrise_sunset_match_open_meteo_over_half_a_year(city: str) -> None:
    # 2025-12-21〜2026-06-21 の毎日（冬至から夏至まで）。
    expected = open_meteo_sun_times(f"archive_sun_{city}.json", city)
    assert len(expected) == 183

    _assert_sun_times_match(city, f"archive_sun_{city}.json")


# --- USNO の薄明・南中 ---


# 届かない日（ベルリンの夏至の天文薄明）は、下の「is_none_in_berlin_summer」のテストで確かめる。
TWILIGHT_CASES = [
    (city, kind, day)
    for city in ("tokyo", "berlin")
    for kind in TWILIGHT_ALTITUDES
    for day in REFERENCE_DAYS
    if (city, kind, day) != ("berlin", "astronomical", date(2026, 6, 21))
]


@pytest.mark.parametrize(("city", "kind", "day"), TWILIGHT_CASES)
def test_twilight_times_match_reference(city: str, kind: str, day: date) -> None:
    dawn, dusk = usno_twilight(city, kind)[day]
    assert dawn is not None and dusk is not None
    latitude, longitude = coordinates(city)

    crossing = solar.altitude_crossing(latitude, longitude, day, TWILIGHT_ALTITUDES[kind])

    _assert_close(crossing.morning, dawn)
    _assert_close(crossing.evening, dusk)


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
@pytest.mark.parametrize("day", REFERENCE_DAYS)
def test_solar_noon_matches_reference(city: str, day: date) -> None:
    _, longitude = coordinates(city)

    _assert_close(solar.solar_noon(longitude, day), usno_transit(city, day))


def test_astronomical_twilight_is_none_in_berlin_summer() -> None:
    day = date(2026, 6, 21)
    latitude, longitude = coordinates("berlin")
    assert usno_twilight("berlin", "astronomical")[day] == (None, None)
    assert None not in usno_twilight("berlin", "nautical")[day]

    astronomical = solar.altitude_crossing(latitude, longitude, day, -18.0)
    nautical = solar.altitude_crossing(latitude, longitude, day, -12.0)

    assert (astronomical.morning, astronomical.evening) == (None, None)
    assert nautical.morning is not None and nautical.evening is not None


def test_astronomical_twilight_boundary_dates_in_berlin() -> None:
    # 天文薄明が終わらない期間の両端。期間の中の日は None、外側で朝夕がそろう最も近い日は値あり。
    table = usno_twilight("berlin", "astronomical")
    never_dark = sorted(day for day, times in table.items() if times == (None, None))
    both = {day for day, times in table.items() if None not in times}
    last_before = max(day for day in both if day < never_dark[0])
    first_after = min(day for day in both if day > never_dark[-1])
    latitude, longitude = coordinates("berlin")

    for day in (never_dark[0], never_dark[-1]):
        crossing = solar.altitude_crossing(latitude, longitude, day, -18.0)
        assert (crossing.morning, crossing.evening) == (None, None), day
    for day in (last_before, first_after):
        crossing = solar.altitude_crossing(latitude, longitude, day, -18.0)
        assert crossing.morning is not None and crossing.evening is not None, day


def test_event_after_local_midnight_belongs_to_the_evening() -> None:
    # ベルリンの 5 月：天文薄明の終わりが現地（夏時間）の 0 時を過ぎる最初の日。
    table = usno_twilight("berlin", "astronomical")
    day, dusk = next(
        (day, dusk)
        for day, (_, dusk) in sorted(table.items())
        if day.month == 5 and dusk is not None and dusk.astimezone(BERLIN).date() > day
    )
    latitude, longitude = coordinates("berlin")

    crossing = solar.altitude_crossing(latitude, longitude, day, -18.0)

    _assert_close(crossing.evening, dusk)
    assert crossing.evening is not None
    assert crossing.evening.astimezone(BERLIN).date() == day + timedelta(days=1)


# --- 外部の値を使わない確認（値どうしの関係） ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
@pytest.mark.parametrize("month", range(1, 13))
def test_event_order_is_consistent(city: str, month: int) -> None:
    day = date(2026, month, 15)
    latitude, longitude = coordinates(city)
    crossings = [
        solar.altitude_crossing(latitude, longitude, day, altitude)
        for altitude in (-18.0, -12.0, -6.0, SUNRISE_ALTITUDE)
    ]

    mornings = [crossing.morning for crossing in crossings]
    evenings = [crossing.evening for crossing in reversed(crossings)]
    events = [*mornings, solar.solar_noon(longitude, day), *evenings]
    present = [event for event in events if event is not None]

    # 日の出・日の入りと市民・航海薄明は、対象の 2 都市では毎日ある。
    assert None not in events[1:-1]
    assert present == sorted(present)
    assert len(set(present)) == len(present)


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
@pytest.mark.parametrize("day", REFERENCE_DAYS)
def test_noon_elevation_is_the_daily_maximum(city: str, day: date) -> None:
    latitude, longitude = coordinates(city)
    noon = solar.solar_noon(longitude, day)

    at_noon = solar.solar_elevation_deg(latitude, longitude, noon)

    for minutes in (-360, -60, -10, 10, 60, 360):
        other = solar.solar_elevation_deg(latitude, longitude, noon + timedelta(minutes=minutes))
        assert at_noon > other


@pytest.mark.parametrize("day", [date(2026, 6, 21), date(2026, 12, 21)])
def test_sun_never_reaches_altitude_returns_none(day: date) -> None:
    # 北緯 78°：夏至は一日中沈まず、冬至は一日中昇らない。例外にしない。
    crossing = solar.altitude_crossing(78.0, 15.0, day, SUNRISE_ALTITUDE)

    assert (crossing.morning, crossing.evening) == (None, None)


def test_solar_functions_return_utc() -> None:
    latitude, longitude = coordinates("tokyo")
    day = date(2026, 10, 14)

    noon = solar.solar_noon(longitude, day)
    crossing = solar.altitude_crossing(latitude, longitude, day, SUNRISE_ALTITUDE)

    for value in (noon, crossing.morning, crossing.evening):
        assert value is not None
        assert value.utcoffset() == timedelta(0)
    # 南中は、その現地の日付の中にある。
    assert noon.astimezone(ZoneInfo("Asia/Tokyo")).date() == day


def test_solar_functions_reject_naive_datetime() -> None:
    naive = datetime(2026, 10, 14, 3, 0, 0)

    with pytest.raises(ValueError):
        solar.solar_elevation_deg(35.55, 139.78, naive)
    with pytest.raises(ValueError):
        solar.solar_declination_deg(naive)
    with pytest.raises(ValueError):
        solar.equation_of_time_min(naive)


def test_solar_elevation_is_the_same_for_the_same_instant() -> None:
    at_utc = datetime(2026, 10, 14, 3, 0, 0, tzinfo=UTC)
    at_jst = at_utc.astimezone(timezone(timedelta(hours=9)))

    assert solar.solar_elevation_deg(35.55, 139.78, at_jst) == solar.solar_elevation_deg(
        35.55, 139.78, at_utc
    )
