"""気象（1 時間ごと）と METAR を時刻で結合し、学習用の表を作る。"""

import os
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from ml import archive, metar
from ml.archive import TIME_UNIT

# 正時から、この範囲にある METAR だけを付ける（ちょうどは含める）。
TOLERANCE = pd.Timedelta(minutes=30)
METAR_TIME = "metar_observed_at"
COLUMNS = [
    "city",
    *archive.COLUMNS,
    METAR_TIME,
    *(column for column in metar.COLUMNS if column not in ("station", "observed_at")),
]


def _utc_time(column: pd.Series, name: str) -> pd.Series:
    dtype = column.dtype
    if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
        raise ValueError(f"{name} must be timezone-aware UTC")
    converted: pd.Series = column.dt.as_unit(TIME_UNIT)
    return converted


def _nearest(hours: pd.DataFrame, reports: pd.DataFrame, direction: str) -> pd.DataFrame:
    return pd.merge_asof(
        hours,
        reports,
        left_on="time",
        right_on="_report_time",
        direction=direction,  # type: ignore[arg-type]
        tolerance=TOLERANCE,
    )


def join_hourly(weather: pd.DataFrame, metar: pd.DataFrame) -> pd.DataFrame:
    """正時ごとに、前後 30 分以内で最も近い METAR を 1 つ付ける（1 都市ぶん）。

    同じ距離が前後にあるときは前（早いほう）。METAR のない正時は、METAR の列が欠損の行になる。
    """
    left = weather.assign(time=_utc_time(weather["time"], "time"))
    left = left.sort_values("time", kind="stable").reset_index(drop=True)
    reports = metar.drop(columns=["station"], errors="ignore").rename(
        columns={"observed_at": METAR_TIME}
    )
    reports[METAR_TIME] = _utc_time(reports[METAR_TIME], "observed_at")
    reports = reports.sort_values(METAR_TIME, kind="stable").reset_index(drop=True)
    reports["_report_time"] = reports[METAR_TIME]

    hours = left[["time"]]
    before = _nearest(hours, reports, "backward")
    after = _nearest(hours, reports, "forward")
    use_before = before[METAR_TIME].notna() & (
        after[METAR_TIME].isna()
        | ((hours["time"] - before[METAR_TIME]) <= (after[METAR_TIME] - hours["time"]))
    )
    picked = pd.concat([before[use_before], after[~use_before]]).sort_index()
    picked = picked.drop(columns=["time", "_report_time"])
    return pd.concat([left, picked], axis=1)


def build_dataset(parts: Mapping[str, tuple[pd.DataFrame, pd.DataFrame]]) -> pd.DataFrame:
    """都市ごとの（気象, METAR）を結合して 1 つの表にする。行の順は 都市 → 時刻。"""
    tables = []
    for city in sorted(parts):
        weather, reports = parts[city]
        joined = join_hourly(weather, reports)
        joined.insert(0, "city", pd.Series([city] * len(joined), dtype="str"))
        tables.append(joined)
    return pd.concat(tables, ignore_index=True)[COLUMNS]


def validate_dataset(dataset: pd.DataFrame) -> None:
    """保存してよい形か確かめる。違えば ValueError。"""
    if list(dataset.columns) != COLUMNS:
        raise ValueError("dataset does not have the expected columns")
    if dataset.empty:
        raise ValueError("dataset is empty")
    for name in ("time", METAR_TIME):
        _utc_time(dataset[name], name)
    if dataset.duplicated(["city", "time"]).any():
        raise ValueError("dataset has duplicated city and time")
    ordered = dataset.sort_values(["city", "time"], kind="stable")
    if list(ordered.index) != list(dataset.index):
        raise ValueError("dataset is not sorted by city and time")


def save_dataset(dataset: pd.DataFrame, path: Path) -> None:
    validate_dataset(dataset)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        dataset.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_dataset(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)
