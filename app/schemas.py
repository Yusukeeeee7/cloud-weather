import datetime as dt
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


class HourlyForecast(BaseModel):
    time: datetime
    weather_code: int
    weather: WeatherCategory
    temperature_c: float
    precipitation_probability: int
    precipitation_mm: float
    cloud_cover: CloudCover


class DailyForecast(BaseModel):
    # 現地の日付。sunrise・sunset は UTC。
    date: dt.date
    weather_code: int
    weather: WeatherCategory
    temperature_max_c: float
    temperature_min_c: float
    precipitation_probability_max: int
    precipitation_sum_mm: float
    sunrise: datetime
    sunset: datetime


class WeatherResponse(BaseModel):
    city: str
    timezone: str
    current: CurrentWeather
    hourly: list[HourlyForecast]
    daily: list[DailyForecast]
    source: Literal["open-meteo"]
    fetched_at: datetime
    # 外部APIを呼ばずにキャッシュから返したとき true。
    cached: bool


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
