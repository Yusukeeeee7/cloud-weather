from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.services.weather_codes import WeatherCategory


class CloudCover(BaseModel):
    total: int
    low: int
    mid: int
    high: int


class CurrentWeather(BaseModel):
    time: datetime
    weather_code: int
    weather: WeatherCategory
    temperature_c: float
    apparent_temperature_c: float
    dew_point_c: float
    relative_humidity: int
    precipitation_mm: float
    wind_speed_ms: float
    cloud_cover: CloudCover


class WeatherResponse(BaseModel):
    city: str
    timezone: str
    current: CurrentWeather
    source: Literal["open-meteo"]
    fetched_at: datetime


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
