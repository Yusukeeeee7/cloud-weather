"""特徴量の作成。学習（ノートブック）と推論（API）で同じものを使う。"""

import math
from typing import Literal

import pandas as pd

from app.cities import CITIES, City
from app.services.solar import solar_elevation_deg

SEASONS = ("winter", "spring", "summer", "autumn")

# Open-Meteo の値をそのまま使う列。
_WEATHER_FEATURES = (
    "temperature_c",
    "dew_point_c",
    "relative_humidity",
    "pressure_msl_hpa",
    "wind_speed_ms",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "precipitation_mm",
)
# モデルに渡す列の名前と順。docs/spec.md「9. 特徴量」。
FEATURE_NAMES: tuple[str, ...] = (
    "temperature_c",
    "dew_point_c",
    "relative_humidity",
    "pressure_msl_hpa",
    "wind_speed_ms",
    "dew_point_spread_c",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "local_hour_sin",
    "local_hour_cos",
    "day_of_year_sin",
    "day_of_year_cos",
    "solar_elevation_deg",
    "city_code",
    "precipitation_mm",
)
_HOURS_PER_DAY = 24
_DAYS_PER_YEAR = 365.25


def _local_time(
    observations: pd.DataFrame, part: Literal["hour", "month", "dayofyear"]
) -> pd.Series:
    """`time`（UTC）を `city` のタイムゾーンに直し、その時・月・年の何日目かを返す。"""
    time = observations["time"]
    dtype = time.dtype
    if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
        raise ValueError("time must be timezone-aware UTC")
    values = pd.Series(0, index=observations.index, dtype="int64")
    for name in observations["city"].unique():
        timezone = CITIES[City(name)].timezone
        rows = (observations["city"] == name).to_numpy()
        local = time[rows].dt.tz_convert(timezone).dt
        values.iloc[rows] = getattr(local, part).to_numpy()
    return values


def local_hour(observations: pd.DataFrame) -> pd.Series:
    """`time`（UTC）を、`city` のタイムゾーンでの時（0〜23）にする。"""
    return _local_time(observations, "hour").rename("local_hour")


def season(observations: pd.DataFrame) -> pd.Series:
    """現地の月から季節を付ける（冬 12〜2 月、春 3〜5 月、夏 6〜8 月、秋 9〜11 月）。"""
    month = _local_time(observations, "month")
    names = {number: SEASONS[(number % 12) // 3] for number in range(1, 13)}
    return month.map(names).astype("str").rename("season")


def dew_point_spread_c(temperature_c: pd.Series, dew_point_c: pd.Series) -> pd.Series:
    """気温 − 露点（℃）。露点のほうが高ければ負のまま返す。"""
    return (temperature_c - dew_point_c).astype("float64")


def _cyclic(values: pd.Series, period: float) -> tuple[pd.Series, pd.Series]:
    """`period` で 1 周する値の（sin, cos）。端（23 時と 0 時など）が隣り合う。"""
    angle = values * (2 * math.pi / period)
    return angle.map(math.sin).astype("float64"), angle.map(math.cos).astype("float64")


def solar_elevation_series(observations: pd.DataFrame) -> pd.Series:
    """その都市・その時刻の太陽の高度（`/daylight` と同じ計算）。`ml/climate.py` でも使う。"""
    places = {name: CITIES[City(name)] for name in observations["city"].unique()}
    values = [
        solar_elevation_deg(places[name].latitude, places[name].longitude, at)
        for name, at in zip(observations["city"], observations["time"], strict=True)
    ]
    return pd.Series(values, index=observations.index, dtype="float64")


def features(observations: pd.DataFrame) -> pd.DataFrame:
    """特徴量の表（列は `FEATURE_NAMES` の順）。

    `city`・`time`（UTC）と Open-Meteo の列だけで作る（METAR の列は使わない）。
    各行は、その行の値だけで決まる。欠損は埋めない。
    """
    required = ("city", "time", *_WEATHER_FEATURES)
    if any(name not in observations.columns for name in required):
        raise ValueError("observations do not have the expected columns")
    hour_sin, hour_cos = _cyclic(_local_time(observations, "hour"), _HOURS_PER_DAY)
    day_sin, day_cos = _cyclic(_local_time(observations, "dayofyear"), _DAYS_PER_YEAR)
    codes = {city.value: code for code, city in enumerate(City)}
    table = observations[list(_WEATHER_FEATURES)].astype("float64")
    table = table.assign(
        dew_point_spread_c=dew_point_spread_c(
            observations["temperature_c"], observations["dew_point_c"]
        ),
        local_hour_sin=hour_sin,
        local_hour_cos=hour_cos,
        day_of_year_sin=day_sin,
        day_of_year_cos=day_cos,
        solar_elevation_deg=solar_elevation_series(observations),
        city_code=observations["city"].map(codes).astype("int64"),
    )
    return table[list(FEATURE_NAMES)]
