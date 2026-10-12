from dataclasses import dataclass
from enum import StrEnum


class City(StrEnum):
    TOKYO = "tokyo"
    BERLIN = "berlin"


@dataclass(frozen=True)
class CityInfo:
    latitude: float
    longitude: float
    timezone: str


# docs/spec.md「3. 対象地点」の値。
CITIES: dict[City, CityInfo] = {
    City.TOKYO: CityInfo(latitude=35.55, longitude=139.78, timezone="Asia/Tokyo"),
    City.BERLIN: CityInfo(latitude=52.36, longitude=13.50, timezone="Europe/Berlin"),
}
