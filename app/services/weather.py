import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.cities import CITIES, City
from app.clients.open_meteo import OpenMeteoClient
from app.errors import UpstreamError
from app.schemas import CloudCover, CurrentWeather, WeatherResponse
from app.services.forecast import (
    INVALID_RESPONSE_ERRORS,
    build_daily,
    build_hourly,
    from_unix,
)
from app.services.weather_codes import classify_weather_code

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]


class _RawCurrent(BaseModel):
    """Open-Meteo の current のうち、使う項目。欠けている・null・型違いは検証で落とす。"""

    # 数値の文字列や真偽値を数値として受け付けない。
    model_config = ConfigDict(strict=True)

    # UNIX 秒（timeformat=unixtime）。
    time: int
    temperature_2m: float
    apparent_temperature: float
    dew_point_2m: float
    relative_humidity_2m: int
    precipitation: float
    weather_code: int
    cloud_cover: int
    cloud_cover_low: int
    cloud_cover_mid: int
    cloud_cover_high: int
    wind_speed_10m: float


def utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_current(raw: Mapping[str, Any]) -> tuple[_RawCurrent, datetime]:
    try:
        current = _RawCurrent.model_validate(raw.get("current"))
        return current, from_unix(current.time)
    except INVALID_RESPONSE_ERRORS as exc:
        logger.warning("open-meteo response is missing required current fields")
        raise UpstreamError("invalid current") from exc


def build_weather_response(
    city: City, raw: Mapping[str, Any], fetched_at: datetime
) -> WeatherResponse:
    current, time = _parse_current(raw)
    return WeatherResponse(
        city=city.value,
        timezone=CITIES[city].timezone,
        current=CurrentWeather(
            time=time,
            weather_code=current.weather_code,
            weather=classify_weather_code(current.weather_code),
            temperature_c=current.temperature_2m,
            apparent_temperature_c=current.apparent_temperature,
            dew_point_c=current.dew_point_2m,
            relative_humidity=current.relative_humidity_2m,
            precipitation_mm=current.precipitation,
            wind_speed_ms=current.wind_speed_10m,
            cloud_cover=CloudCover(
                total=current.cloud_cover,
                low=current.cloud_cover_low,
                mid=current.cloud_cover_mid,
                high=current.cloud_cover_high,
            ),
        ),
        hourly=build_hourly(raw, fetched_at),
        daily=build_daily(raw),
        source="open-meteo",
        fetched_at=fetched_at.astimezone(UTC).replace(microsecond=0),
    )


async def get_weather(city: City, client: OpenMeteoClient, clock: Clock) -> WeatherResponse:
    raw = await client.fetch_forecast(city)
    return build_weather_response(city, raw, clock())
