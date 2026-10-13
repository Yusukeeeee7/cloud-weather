"""特徴量の作成。学習（ノートブック）と推論（API）で同じものを使う。"""

import pandas as pd

from app.cities import CITIES, City

SEASONS = ("winter", "spring", "summer", "autumn")


def _local_time(observations: pd.DataFrame, part: str) -> pd.Series:
    """`time`（UTC）を `city` のタイムゾーンに直し、その時（hour）または月（month）を返す。"""
    time = observations["time"]
    dtype = time.dtype
    if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
        raise ValueError("time must be timezone-aware UTC")
    values = pd.Series(0, index=observations.index, dtype="int64")
    for name in observations["city"].unique():
        timezone = CITIES[City(name)].timezone
        rows = (observations["city"] == name).to_numpy()
        local = time[rows].dt.tz_convert(timezone).dt
        values.iloc[rows] = (local.hour if part == "hour" else local.month).to_numpy()
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
