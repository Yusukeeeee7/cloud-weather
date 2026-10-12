from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.cities import CITIES, City
from app.schemas import DaylightResponse, Twilight, TwilightPeriod
from app.services import solar
from app.services.solar import AltitudeCrossing
from app.services.weather import Clock

# docs/spec.md「用語の定義」の太陽の高度（度）。
SUNRISE_ALTITUDE_DEG = -0.833
CIVIL_ALTITUDE_DEG = -6.0
NAUTICAL_ALTITUDE_DEG = -12.0
ASTRONOMICAL_ALTITUDE_DEG = -18.0


def local_today(city: City, now: datetime) -> date:
    return now.astimezone(ZoneInfo(CITIES[city].timezone)).date()


def _round_to_second(value: datetime) -> datetime:
    return (value + timedelta(milliseconds=500)).replace(microsecond=0)


def _rounded(crossing: AltitudeCrossing) -> AltitudeCrossing:
    morning, evening = crossing.morning, crossing.evening
    return AltitudeCrossing(
        morning=None if morning is None else _round_to_second(morning),
        evening=None if evening is None else _round_to_second(evening),
    )


def _hours_between(crossing: AltitudeCrossing, noon_is_above: bool) -> float:
    """朝の通過から夕の通過まで。通らない日は、ずっと上なら 24、ずっと下なら 0。

    朝・夕の片方だけがない日（その高度にちょうど届くかどうかの境目の日）の値は決めていない
    （いまは通らない日と同じ扱い）。対象の 2 都市の日の出入り・市民薄明では起きない。
    """
    if crossing.morning is None or crossing.evening is None:
        return 24.0 if noon_is_above else 0.0
    return (crossing.evening - crossing.morning) / timedelta(hours=1)


def hours_above(latitude: float, longitude: float, day: date, altitude_deg: float) -> float:
    """その日に、太陽が `altitude_deg` より上にある時間。"""
    noon = solar.solar_noon(longitude, day)
    noon_is_above = solar.solar_elevation_deg(latitude, longitude, noon) > altitude_deg
    crossing = solar.altitude_crossing(latitude, longitude, day, altitude_deg)
    return _hours_between(crossing, noon_is_above)


def _period(crossing: AltitudeCrossing) -> TwilightPeriod:
    return TwilightPeriod(dawn=crossing.morning, dusk=crossing.evening)


def get_daylight(city: City, day: date | None, clock: Clock) -> DaylightResponse:
    info = CITIES[city]
    target = local_today(city, clock()) if day is None else day

    def crossing(altitude_deg: float) -> AltitudeCrossing:
        return _rounded(
            solar.altitude_crossing(info.latitude, info.longitude, target, altitude_deg)
        )

    noon = solar.solar_noon(info.longitude, target)
    noon_elevation = solar.solar_elevation_deg(info.latitude, info.longitude, noon)
    sun, civil = crossing(SUNRISE_ALTITUDE_DEG), crossing(CIVIL_ALTITUDE_DEG)
    # 時間は、応答に入れる（秒に丸めた）時刻から出す。
    daylight_hours = round(_hours_between(sun, noon_elevation > SUNRISE_ALTITUDE_DEG), 2)
    civil_hours = _hours_between(civil, noon_elevation > CIVIL_ALTITUDE_DEG)
    return DaylightResponse(
        city=city.value,
        date=target,
        sunrise=sun.morning,
        sunset=sun.evening,
        twilight=Twilight(
            civil=_period(civil),
            nautical=_period(crossing(NAUTICAL_ALTITUDE_DEG)),
            astronomical=_period(crossing(ASTRONOMICAL_ALTITUDE_DEG)),
        ),
        daylight_hours=daylight_hours,
        night_hours=round(24 - daylight_hours, 2),
        dark_hours=round(24 - civil_hours, 2),
        solar_noon=_round_to_second(noon),
        solar_noon_elevation_deg=round(noon_elevation, 1),
        method="noaa-solar-calculator",
    )
