"""太陽計算のテストで使う、外部の値（tests/fixtures/）の読み出し。

期待値はここで読んだ値だけを使う（AI が計算して作らない）。出典は tests/fixtures/README.md。
"""

import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.cities import CITIES, City
from tests.conftest import FIXTURES_DIR

# spec.md「精度」：±2 分以内。
TOLERANCE = timedelta(minutes=2)

TwilightTimes = tuple[datetime | None, datetime | None]

_DAY_ROW = re.compile(r"^(\d\d)  ")
_ZONE = re.compile(r"Zone:\s+(\d+)h East of Greenwich")
_MONTH_WIDTH = 11
_FIRST_MONTH_COLUMN = 4


def _load_json(*parts: str) -> Any:
    return json.loads(FIXTURES_DIR.joinpath(*parts).read_text(encoding="utf-8"))


def coordinates(city: str) -> tuple[float, float]:
    info = CITIES[City(city)]
    return info.latitude, info.longitude


def open_meteo_sun_times(name: str, city: str) -> dict[date, tuple[datetime, datetime]]:
    """Open-Meteo の daily.sunrise・sunset（UNIX 秒）。キーは、日の出が属する現地の日付。"""
    daily = _load_json("open_meteo", name)["daily"]
    zone = ZoneInfo(CITIES[City(city)].timezone)
    result: dict[date, tuple[datetime, datetime]] = {}
    for sunrise_s, sunset_s in zip(daily["sunrise"], daily["sunset"], strict=True):
        sunrise = datetime.fromtimestamp(sunrise_s, UTC)
        sunset = datetime.fromtimestamp(sunset_s, UTC)
        result[sunrise.astimezone(zone).date()] = (sunrise, sunset)
    return result


def _usno_time(day: date, text: str, zone_hours: int) -> datetime | None:
    # 「////」（その高度まで沈まない）と空欄は None。
    if not text.isdigit():
        return None
    local = datetime(day.year, day.month, day.day, int(text[:2]), int(text[2:]), tzinfo=UTC)
    return local - timedelta(hours=zone_hours)


def usno_twilight(city: str, kind: str, year: int = 2026) -> dict[date, TwilightTimes]:
    """USNO の 1 年ぶんの表（分単位）。表は現地の標準時なので UTC に直す。キーは表の日付。"""
    path = FIXTURES_DIR / "usno" / f"year_{year}_{city}_{kind}.html"
    text = path.read_text(encoding="utf-8")
    zone = _ZONE.search(text)
    assert zone is not None, "zone line not found in the USNO table"
    zone_hours = int(zone.group(1))
    result: dict[date, TwilightTimes] = {}
    for line in text.splitlines():
        row = _DAY_ROW.match(line)
        if row is None:
            continue
        for month in range(1, 13):
            start = _FIRST_MONTH_COLUMN + _MONTH_WIDTH * (month - 1)
            begin, end = line[start : start + 4], line[start + 5 : start + 9]
            if not (begin.strip() or end.strip()):
                # その月にない日（2 月 30 日など）。
                continue
            day = date(year, month, int(row.group(1)))
            assert day not in result, "unexpected continuation line in the USNO table"
            result[day] = (_usno_time(day, begin, zone_hours), _usno_time(day, end, zone_hours))
    return result


def usno_transit(city: str, day: date) -> datetime:
    """USNO の 1 日ぶんのデータの南中（Upper Transit。UT、分単位）。"""
    data = _load_json("usno", f"oneday_{city}_{day.isoformat()}.json")["properties"]["data"]
    assert data["tz"] == 0.0
    assert (data["year"], data["month"], data["day"]) == (day.year, day.month, day.day)
    times = {item["phen"]: item["time"] for item in data["sundata"]}
    hour, minute = times["Upper Transit"].split(":")
    return datetime(day.year, day.month, day.day, int(hour), int(minute), tzinfo=UTC)


class NoaaSheet:
    """NOAA のスプレッドシート（NOAA_Solar_Calculations_day）に入っている計算済みの値。"""

    def __init__(self) -> None:
        raw = _load_json("noaa", "solar_calculations_day.json")
        inputs = raw["inputs"]
        self.latitude: float = inputs["Latitude (+ to N)"]
        self.longitude: float = inputs["Longitude (+ to E)"]
        self.zone_hours: float = inputs["Time Zone (+ to E)"]
        self.day = date.fromisoformat(inputs["Date"])
        self.rows: list[dict[str, Any]] = raw["rows"]

    def to_utc(self, day_fraction: float) -> datetime:
        """「現地の 0 時からの日数」（表の時刻の列）を UTC の時刻にする。"""
        midnight = datetime(self.day.year, self.day.month, self.day.day, tzinfo=UTC)
        return midnight + timedelta(days=day_fraction) - timedelta(hours=self.zone_hours)

    def row_time(self, row: dict[str, Any]) -> datetime:
        return self.to_utc(row["Time (past local midnight)"])

    def event_time(self, column: str) -> datetime:
        """日の出・日の入り・南中の列の値。その時刻にいちばん近い行の値を使う。"""

        def distance(row: dict[str, Any]) -> float:
            return abs(float(row[column]) - float(row["Time (past local midnight)"]))

        return self.to_utc(min(self.rows, key=distance)[column])
