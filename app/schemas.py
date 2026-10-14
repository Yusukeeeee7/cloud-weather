import datetime as dt
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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
    # キャッシュの値を返したとき true。
    cached: bool
    # 外部APIが失敗し、TTL を過ぎた保存値を返したとき true。
    stale: bool


class TwilightPeriod(BaseModel):
    # 太陽がその高度まで沈まない（または昇らない）日は null。
    dawn: datetime | None
    dusk: datetime | None


class Twilight(BaseModel):
    civil: TwilightPeriod
    nautical: TwilightPeriod
    astronomical: TwilightPeriod


class DaylightResponse(BaseModel):
    city: str
    # 現地の日付。時刻はすべて UTC。
    date: dt.date
    sunrise: datetime | None
    sunset: datetime | None
    twilight: Twilight
    daylight_hours: float
    night_hours: float
    dark_hours: float
    solar_noon: datetime
    solar_noon_elevation_deg: float
    method: Literal["noaa-solar-calculator"]


class CloudBaseResponse(BaseModel):
    city: str
    # 予測した時刻（UTC の正時）。
    valid_at: datetime = Field(description="Hour (UTC) the prediction is for.")
    # どちらも 0〜1,524 m。1,524 は「それより下にシーリングがない」。
    predicted_m: int = Field(
        description="Predicted ceiling in metres, 0-1524. 1524 means no ceiling below 1524 m."
    )
    baseline_m: int = Field(
        description="Rule of thumb 125 x (temperature - dew point) in metres, limited to 0-1524."
    )
    model_version: str


class CloudHistoryHour(BaseModel):
    time: datetime
    cloud_cover: CloudCover


class CloudHistoryResponse(BaseModel):
    city: str
    # 古い順に 24 件。最後は現在以前の最も近い正時。値は過去の予報の保存値（観測ではない）。
    hourly: list[CloudHistoryHour] = Field(
        description=(
            "Cloud cover (%) for the past 24 hours, oldest first, ending at the latest hour "
            "(UTC) at or before now. Values are archived forecasts, not observations."
        )
    )


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
