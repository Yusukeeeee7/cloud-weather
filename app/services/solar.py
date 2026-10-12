"""太陽位置の計算（NOAA Solar Calculator のスプレッドシートの式）。

入力は緯度・経度（度。北・東が正）と UTC の日付・時刻、出力は UTC の時刻か角度（度）。
都市や API の形は知らない（`ml/` からも使う）。

出典：NOAA Global Monitoring Laboratory「NOAA_Solar_Calculations_day」
（https://gml.noaa.gov/grad/solcalc/calcdetails.html）。
式は Jean Meeus『Astronomical Algorithms』による。
係数はスプレッドシートの各列の式のまま。薄明は、日の出の時角の式の高度を替えて求める
（この置き換えは NOAA の資料にはない）。
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from math import acos, asin, cos, degrees, radians, sin, tan

# ユリウス日 2451545.0（スプレッドシートの「Julian Century」の基準）。
_J2000 = datetime(2000, 1, 1, 12, tzinfo=UTC)
_DAYS_PER_CENTURY = 36525
_MINUTES_PER_DEGREE = 4
# 時刻を求め直す回数（赤緯・均時差を、求めた時刻のものに置き換える）。
_REFINEMENTS = 3


@dataclass(frozen=True)
class AltitudeCrossing:
    """太陽がある高度を通る時刻。朝（上向き）と夕（下向き）。通らなければ None。"""

    morning: datetime | None
    evening: datetime | None


def _julian_century(at: datetime) -> float:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return (at - _J2000) / timedelta(days=1) / _DAYS_PER_CENTURY


def _mean_longitude_deg(t: float) -> float:
    return (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360


def _mean_anomaly_deg(t: float) -> float:
    return 357.52911 + t * (35999.05029 - 0.0001537 * t)


def _eccentricity(t: float) -> float:
    return 0.016708634 - t * (0.000042037 + 0.0000001267 * t)


def _apparent_longitude_deg(t: float) -> float:
    anomaly = radians(_mean_anomaly_deg(t))
    center = (
        sin(anomaly) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + sin(2 * anomaly) * (0.019993 - 0.000101 * t)
        + sin(3 * anomaly) * 0.000289
    )
    true_longitude = _mean_longitude_deg(t) + center
    return true_longitude - 0.00569 - 0.00478 * sin(radians(125.04 - 1934.136 * t))


def _obliquity_deg(t: float) -> float:
    mean = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    return mean + 0.00256 * cos(radians(125.04 - 1934.136 * t))


def _declination_deg(t: float) -> float:
    obliquity = radians(_obliquity_deg(t))
    return degrees(asin(sin(obliquity) * sin(radians(_apparent_longitude_deg(t)))))


def _equation_of_time_min(t: float) -> float:
    longitude = radians(_mean_longitude_deg(t))
    anomaly = radians(_mean_anomaly_deg(t))
    eccentricity = _eccentricity(t)
    y = tan(radians(_obliquity_deg(t) / 2)) ** 2
    return _MINUTES_PER_DEGREE * degrees(
        y * sin(2 * longitude)
        - 2 * eccentricity * sin(anomaly)
        + 4 * eccentricity * y * sin(anomaly) * cos(2 * longitude)
        - 0.5 * y * y * sin(4 * longitude)
        - 1.25 * eccentricity * eccentricity * sin(2 * anomaly)
    )


def solar_declination_deg(at: datetime) -> float:
    return _declination_deg(_julian_century(at))


def equation_of_time_min(at: datetime) -> float:
    return _equation_of_time_min(_julian_century(at))


def solar_elevation_deg(latitude: float, longitude: float, at: datetime) -> float:
    """太陽の中心の高度。大気差の補正は入れない。"""
    t = _julian_century(at)
    utc = at.astimezone(UTC)
    minutes = (utc - utc.replace(hour=0, minute=0, second=0, microsecond=0)) / timedelta(minutes=1)
    true_solar_time = (minutes + _equation_of_time_min(t) + _MINUTES_PER_DEGREE * longitude) % 1440
    hour_angle = radians(true_solar_time / _MINUTES_PER_DEGREE - 180)
    declination = radians(_declination_deg(t))
    lat = radians(latitude)
    cos_zenith = sin(lat) * sin(declination) + cos(lat) * cos(declination) * cos(hour_angle)
    return 90 - degrees(acos(max(-1.0, min(1.0, cos_zenith))))


def _hour_angle_deg(latitude: float, declination_deg: float, altitude_deg: float) -> float | None:
    """太陽がその高度にあるときの時角。その高度を通らなければ None。"""
    lat, declination = radians(latitude), radians(declination_deg)
    cos_hour_angle = sin(radians(altitude_deg)) / (cos(lat) * cos(declination)) - tan(lat) * tan(
        declination
    )
    if not -1.0 <= cos_hour_angle <= 1.0:
        return None
    return degrees(acos(cos_hour_angle))


def _midnight_utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _noon_at(longitude: float, day: date, t: float) -> datetime:
    minutes = 720 - _MINUTES_PER_DEGREE * longitude - _equation_of_time_min(t)
    return _midnight_utc(day) + timedelta(minutes=minutes)


def solar_noon(longitude: float, day: date) -> datetime:
    """`day`（その経度での日付）の南中の時刻。"""
    noon = _midnight_utc(day) + timedelta(minutes=720 - _MINUTES_PER_DEGREE * longitude)
    for _ in range(_REFINEMENTS):
        noon = _noon_at(longitude, day, _julian_century(noon))
    return noon


def _crossing_time(
    latitude: float, longitude: float, day: date, altitude_deg: float, direction: int
) -> datetime | None:
    # direction は朝が -1、夕が +1。南中から始めて、求めた時刻の赤緯・均時差で求め直す。
    event = solar_noon(longitude, day)
    for _ in range(_REFINEMENTS):
        t = _julian_century(event)
        hour_angle = _hour_angle_deg(latitude, _declination_deg(t), altitude_deg)
        if hour_angle is None:
            return None
        offset = timedelta(minutes=direction * _MINUTES_PER_DEGREE * hour_angle)
        event = _noon_at(longitude, day, t) + offset
    return event


def altitude_crossing(
    latitude: float, longitude: float, day: date, altitude_deg: float
) -> AltitudeCrossing:
    """`day` の南中の前（朝）と後（夕）に、太陽の中心が `altitude_deg` を通る時刻。"""
    return AltitudeCrossing(
        morning=_crossing_time(latitude, longitude, day, altitude_deg, -1),
        evening=_crossing_time(latitude, longitude, day, altitude_deg, 1),
    )
