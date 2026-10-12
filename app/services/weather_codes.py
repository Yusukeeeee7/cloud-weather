import logging
from enum import StrEnum

logger = logging.getLogger(__name__)


class WeatherCategory(StrEnum):
    CLEAR = "clear"
    PARTLY_CLOUDY = "partly_cloudy"
    CLOUDY = "cloudy"
    FOG = "fog"
    DRIZZLE = "drizzle"
    RAIN = "rain"
    SNOW = "snow"
    THUNDERSTORM = "thunderstorm"
    UNKNOWN = "unknown"


# Open-Meteo の天気コード（WMO）→ 分類。対応表は docs/spec.md「天気の分類」と同じ。
_CODES_BY_CATEGORY: dict[WeatherCategory, tuple[int, ...]] = {
    WeatherCategory.CLEAR: (0, 1),
    WeatherCategory.PARTLY_CLOUDY: (2,),
    WeatherCategory.CLOUDY: (3,),
    WeatherCategory.FOG: (45, 48),
    WeatherCategory.DRIZZLE: (51, 53, 55, 56, 57),
    WeatherCategory.RAIN: (61, 63, 65, 66, 67, 80, 81, 82),
    WeatherCategory.SNOW: (71, 73, 75, 77, 85, 86),
    WeatherCategory.THUNDERSTORM: (95, 96, 99),
}
_CATEGORY_BY_CODE: dict[int, WeatherCategory] = {
    code: category for category, codes in _CODES_BY_CATEGORY.items() for code in codes
}


def classify_weather_code(code: int) -> WeatherCategory:
    category = _CATEGORY_BY_CODE.get(code)
    if category is None:
        logger.warning("unknown weather code: %d", code)
        return WeatherCategory.UNKNOWN
    return category
