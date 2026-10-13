"""学習・検証・テストの分割。docs/spec.md「9. 分割と評価」。"""

import pandas as pd

TRAIN = "train"
VALIDATION = "validation"
TEST = "test"
# 年は UTC。ランダム分割はしない。
SPLIT_YEARS: dict[str, tuple[int, ...]] = {
    TRAIN: (2018, 2019, 2020, 2021, 2022, 2023),
    VALIDATION: (2024,),
    TEST: (2025,),
}


def split(observations: pd.DataFrame) -> pd.Series:
    """`time`（UTC）の年から、分割の名前を付ける。どの分割にも入らない年は欠損。"""
    time = observations["time"]
    dtype = time.dtype
    if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
        raise ValueError("time must be timezone-aware UTC")
    names = {year: name for name, years in SPLIT_YEARS.items() for year in years}
    labels: pd.Series = time.dt.year.map(names).astype("str")
    return labels.rename("split")
