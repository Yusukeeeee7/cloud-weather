from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from app.cities import City
from app.services import daylight
from tests.conftest import FakeClock
from tests.solar_refs import TOLERANCE, coordinates, open_meteo_sun_times

RESPONSE_KEYS = {
    "city",
    "date",
    "sunrise",
    "sunset",
    "twilight",
    "daylight_hours",
    "night_hours",
    "dark_hours",
    "solar_noon",
    "solar_noon_elevation_deg",
    "method",
}
NOON_UTC = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)
# 日の出・日の入りがそれぞれ ±2 分なら、昼の長さは ±4 分。小数 2 桁の丸めのぶんを足す。
HOURS_TOLERANCE = 4 / 60 + 0.005


def _get(city: str, day: date | None, now: datetime = NOON_UTC) -> Any:
    return daylight.get_daylight(City(city), day, FakeClock(now))


def _hours(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_service_builds_spec_shape(city: str) -> None:
    response = _get(city, date(2026, 12, 21))

    body = response.model_dump()
    assert set(body) == RESPONSE_KEYS
    assert set(body["twilight"]) == {"civil", "nautical", "astronomical"}
    for period in body["twilight"].values():
        assert set(period) == {"dawn", "dusk"}
    assert body["city"] == city
    assert body["date"] == date(2026, 12, 21)
    assert body["method"] == "noaa-solar-calculator"


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
@pytest.mark.parametrize("day", [date(2026, 3, 20), date(2026, 6, 21), date(2026, 12, 21)])
def test_service_hours_are_consistent(city: str, day: date) -> None:
    response = _get(city, day)

    # 応答の時刻は秒まで、時間は小数 2 桁。丸めのぶんだけ差を許す。
    assert response.daylight_hours == pytest.approx(
        _hours(response.sunrise, response.sunset),
        abs=0.0051,
    )
    civil = response.twilight.civil
    assert response.dark_hours == pytest.approx(24 - _hours(civil.dawn, civil.dusk), abs=0.0051)
    assert response.night_hours == pytest.approx(
        24 - response.daylight_hours,
        abs=1e-9,
    )
    # 小数 2 桁。
    for value in (response.daylight_hours, response.night_hours, response.dark_hours):
        assert value == round(value, 2)
    assert response.dark_hours < response.night_hours


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_service_matches_open_meteo(city: str) -> None:
    # 既存の fixture（7 日ぶん）の日の出・日の入りと、そこから出した昼の長さ。
    for day, (sunrise, sunset) in open_meteo_sun_times(f"forecast_{city}.json", city).items():
        response = _get(city, day)

        assert abs(response.sunrise - sunrise) <= TOLERANCE
        assert abs(response.sunset - sunset) <= TOLERANCE
        assert response.daylight_hours == pytest.approx(
            _hours(sunrise, sunset), abs=HOURS_TOLERANCE
        )


def test_service_uses_local_date() -> None:
    # 東京の日の出は、UTC では前の日付になる（現地の日付で区切る）。
    day = date(2026, 10, 14)
    sunrise, _ = open_meteo_sun_times("forecast_tokyo.json", "tokyo")[day]
    assert sunrise.date() == day - timedelta(days=1)

    response = _get("tokyo", day)

    assert response.date == day
    assert response.sunrise.date() == day - timedelta(days=1)
    assert response.sunset.date() == day
    assert response.solar_noon.date() == day


@pytest.mark.parametrize(
    ("city", "now", "expected"),
    [
        # 東京は UTC+9：15:00 UTC で日付が変わる。
        ("tokyo", datetime(2026, 10, 12, 14, 59, 59, tzinfo=UTC), date(2026, 10, 12)),
        ("tokyo", datetime(2026, 10, 12, 15, 0, 0, tzinfo=UTC), date(2026, 10, 13)),
        # ベルリンは夏時間で UTC+2：22:00 UTC で日付が変わる。
        ("berlin", datetime(2026, 10, 12, 21, 59, 59, tzinfo=UTC), date(2026, 10, 12)),
        ("berlin", datetime(2026, 10, 12, 22, 0, 0, tzinfo=UTC), date(2026, 10, 13)),
        # 冬は UTC+1：23:00 UTC で日付が変わる。
        ("berlin", datetime(2026, 12, 21, 22, 59, 59, tzinfo=UTC), date(2026, 12, 21)),
        ("berlin", datetime(2026, 12, 21, 23, 0, 0, tzinfo=UTC), date(2026, 12, 22)),
    ],
)
def test_service_default_date_is_local_today(city: str, now: datetime, expected: date) -> None:
    assert daylight.local_today(City(city), now) == expected

    response = _get(city, None, now)

    assert response.date == expected


def test_service_times_are_utc_without_subseconds() -> None:
    response = _get("berlin", date(2026, 12, 21))

    twilight = response.twilight
    times = [
        response.sunrise,
        response.sunset,
        response.solar_noon,
        twilight.civil.dawn,
        twilight.civil.dusk,
        twilight.nautical.dawn,
        twilight.nautical.dusk,
        twilight.astronomical.dawn,
        twilight.astronomical.dusk,
    ]
    for value in times:
        assert value.utcoffset() == timedelta(0)
        assert value.microsecond == 0


def test_service_null_twilight_does_not_raise() -> None:
    # ベルリンの夏至：太陽が −18° まで沈まない。
    response = _get("berlin", date(2026, 6, 21))

    twilight = response.twilight
    assert (twilight.astronomical.dawn, twilight.astronomical.dusk) == (None, None)
    assert None not in (twilight.nautical.dawn, twilight.nautical.dusk)
    assert None not in (twilight.civil.dawn, twilight.civil.dusk)
    assert None not in (response.sunrise, response.sunset)


@pytest.mark.parametrize(
    ("day", "fixture"),
    [
        (date(2026, 10, 25), "sun_berlin_16days.json"),
        (date(2026, 3, 29), "archive_sun_berlin.json"),
    ],
)
def test_service_dst_change_day_hours(day: date, fixture: str) -> None:
    # 切り替え日（現地の 1 日が 25 時間・23 時間）でも、spec のとおり 24 から引く。
    sunrise, sunset = open_meteo_sun_times(fixture, "berlin")[day]

    response = _get("berlin", day)

    assert response.daylight_hours == pytest.approx(_hours(sunrise, sunset), abs=HOURS_TOLERANCE)
    assert response.night_hours == pytest.approx(
        24 - response.daylight_hours,
        abs=1e-9,
    )


def test_service_noon_elevation_has_one_decimal() -> None:
    response = _get("berlin", date(2026, 12, 21))

    elevation = response.solar_noon_elevation_deg
    assert elevation == round(elevation, 1)
    # 冬至のベルリンでも、南中の太陽は地平線より上にある。
    assert 0 < elevation < 90


@pytest.mark.parametrize(
    ("day", "altitude", "expected"),
    [
        # 北緯 78°：夏至は一日中沈まない、冬至は一日中昇らない。
        (date(2026, 6, 21), -0.833, 24.0),
        (date(2026, 12, 21), -0.833, 0.0),
        (date(2026, 6, 21), -6.0, 24.0),
    ],
)
def test_hours_above_when_sun_never_crosses(day: date, altitude: float, expected: float) -> None:
    assert daylight.hours_above(78.0, 15.0, day, altitude) == expected


def test_hours_above_matches_open_meteo() -> None:
    latitude, longitude = coordinates("tokyo")
    day = date(2026, 10, 14)
    sunrise, sunset = open_meteo_sun_times("forecast_tokyo.json", "tokyo")[day]

    actual = daylight.hours_above(latitude, longitude, day, -0.833)

    assert actual == pytest.approx(_hours(sunrise, sunset), abs=4 / 60)
