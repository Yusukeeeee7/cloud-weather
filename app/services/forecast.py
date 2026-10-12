import logging
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.errors import UpstreamError
from app.schemas import CloudCover, DailyForecast, HourlyForecast
from app.services.weather_codes import classify_weather_code

logger = logging.getLogger(__name__)

HOURLY_COUNT = 24
DAILY_COUNT = 7
# Open-Meteo の予報は最大 16 日。これを超える配列は処理しない。
MAX_HOURLY_ROWS = 16 * 24
_HOUR_S = 3600
# 壊れた応答として扱う例外（検証エラー、範囲外の UNIX 秒など）。
INVALID_RESPONSE_ERRORS = (ValidationError, ValueError, OverflowError, OSError)


class _Strict(BaseModel):
    # 数値の文字列や真偽値を数値として受け付けない。
    model_config = ConfigDict(strict=True)


class _RawHourly(_Strict):
    """Open-Meteo の hourly（列ごとの配列）のうち、使う項目。時刻は UNIX 秒。"""

    time: list[int]
    temperature_2m: list[float]
    precipitation_probability: list[int]
    precipitation: list[float]
    weather_code: list[int]
    cloud_cover: list[int]
    cloud_cover_low: list[int]
    cloud_cover_mid: list[int]
    cloud_cover_high: list[int]


class _RawDaily(_Strict):
    """Open-Meteo の daily（列ごとの配列）のうち、使う項目。時刻は UNIX 秒。"""

    time: list[int]
    weather_code: list[int]
    temperature_2m_max: list[float]
    temperature_2m_min: list[float]
    precipitation_sum: list[float]
    precipitation_probability_max: list[int]
    sunrise: list[int]
    sunset: list[int]


class _RawOffset(_Strict):
    utc_offset_seconds: int


def from_unix(seconds: int) -> datetime:
    # timeformat=unixtime で呼んでいるため、Open-Meteo の時刻は UTC の UNIX 秒。
    return datetime.fromtimestamp(seconds, UTC)


def _hourly_columns(raw: Mapping[str, Any]) -> dict[str, list[Any]]:
    section = raw.get("hourly")
    if not isinstance(section, Mapping):
        raise ValueError("hourly is not an object")
    columns: dict[str, list[Any]] = {}
    for name in _RawHourly.model_fields:
        column = section.get(name)
        if not isinstance(column, list):
            raise ValueError("hourly column is missing or not an array")
        columns[name] = column
    rows = len(columns["time"])
    if rows > MAX_HOURLY_ROWS or any(len(column) != rows for column in columns.values()):
        raise ValueError("unexpected hourly column length")
    return columns


def _window_start(times: list[Any], now: datetime) -> int:
    """現在時刻以降の最初の行。そこから HOURLY_COUNT 件が取れなければエラー。"""
    if not all(type(value) is int for value in times):
        raise ValueError("hourly time is not unix seconds")
    threshold = now.timestamp()
    start = next((row for row, value in enumerate(times) if value >= threshold), None)
    if start is None or len(times) - start < HOURLY_COUNT:
        raise ValueError("not enough hourly rows")
    return start


def _parse_hourly(raw: Mapping[str, Any], now: datetime) -> _RawHourly:
    columns = _hourly_columns(raw)
    start = _window_start(columns["time"], now)
    # 返す範囲だけを検証する（先の時刻は値が null のことがあるため）。
    window = _RawHourly.model_validate(
        {name: column[start : start + HOURLY_COUNT] for name, column in columns.items()}
    )
    steps = {later - earlier for earlier, later in zip(window.time, window.time[1:], strict=False)}
    if steps != {_HOUR_S}:
        raise ValueError("hourly times are not consecutive")
    return window


def build_hourly(raw: Mapping[str, Any], now: datetime) -> list[HourlyForecast]:
    try:
        hourly = _parse_hourly(raw, now)
        times = [from_unix(value) for value in hourly.time]
    except INVALID_RESPONSE_ERRORS as exc:
        logger.warning("open-meteo response has invalid hourly data")
        raise UpstreamError("invalid hourly") from exc
    return [
        HourlyForecast(
            time=times[row],
            weather_code=hourly.weather_code[row],
            weather=classify_weather_code(hourly.weather_code[row]),
            temperature_c=hourly.temperature_2m[row],
            precipitation_probability=hourly.precipitation_probability[row],
            precipitation_mm=hourly.precipitation[row],
            cloud_cover=CloudCover(
                total=hourly.cloud_cover[row],
                low=hourly.cloud_cover_low[row],
                mid=hourly.cloud_cover_mid[row],
                high=hourly.cloud_cover_high[row],
            ),
        )
        for row in range(HOURLY_COUNT)
    ]


def _local_date(local_midnight: int, utc_offset_s: int) -> date:
    # daily.time は現地 0 時の瞬間。utc_offset_seconds は取得時点の 1 つの値なので、
    # 夏時間の切り替えをまたぐ日は 1 時間ずれる。現地の正午に進めてから日付を取り、ずれを吸収する。
    return (from_unix(local_midnight) + timedelta(seconds=utc_offset_s, hours=12)).date()


def _local_dates(local_midnights: list[int], utc_offset_s: int) -> list[date]:
    dates = [_local_date(value, utc_offset_s) for value in local_midnights]
    steps = {later - earlier for earlier, later in zip(dates, dates[1:], strict=False)}
    if steps != {timedelta(days=1)}:
        raise ValueError("daily dates are not consecutive")
    return dates


def _parse_daily(raw: Mapping[str, Any]) -> tuple[_RawDaily, int]:
    daily = _RawDaily.model_validate(raw.get("daily"))
    if any(len(column) != DAILY_COUNT for column in daily.model_dump().values()):
        raise ValueError("unexpected daily column length")
    return daily, _RawOffset.model_validate(raw).utc_offset_seconds


def build_daily(raw: Mapping[str, Any]) -> list[DailyForecast]:
    try:
        daily, utc_offset_s = _parse_daily(raw)
        dates = _local_dates(daily.time, utc_offset_s)
        sunrises = [from_unix(value) for value in daily.sunrise]
        sunsets = [from_unix(value) for value in daily.sunset]
    except INVALID_RESPONSE_ERRORS as exc:
        logger.warning("open-meteo response has invalid daily data")
        raise UpstreamError("invalid daily") from exc
    return [
        DailyForecast(
            date=dates[row],
            weather_code=daily.weather_code[row],
            weather=classify_weather_code(daily.weather_code[row]),
            temperature_max_c=daily.temperature_2m_max[row],
            temperature_min_c=daily.temperature_2m_min[row],
            precipitation_probability_max=daily.precipitation_probability_max[row],
            precipitation_sum_mm=daily.precipitation_sum[row],
            sunrise=sunrises[row],
            sunset=sunsets[row],
        )
        for row in range(DAILY_COUNT)
    ]
