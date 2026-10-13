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


def _utc_year(observations: pd.DataFrame) -> pd.Series:
    time = observations["time"]
    dtype = time.dtype
    if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
        raise ValueError("time must be timezone-aware UTC")
    years: pd.Series = time.dt.year
    return years


def split(observations: pd.DataFrame) -> pd.Series:
    """`time`（UTC）の年から、分割の名前を付ける。どの分割にも入らない年は欠損。"""
    names = {year: name for name, years in SPLIT_YEARS.items() for year in years}
    labels: pd.Series = _utc_year(observations).map(names).astype("str")
    return labels.rename("split")


# 学習の年を短くした場合（#11 で 1 回だけ、検証の年の MAE で 6 年と比べる）。
TRAIN_YEARS_SHORT: tuple[int, ...] = (2021, 2022, 2023)


# 設定を選ぶときの検証（#17）。名前 → （学習の年, 検証の年）。テストの年は入れない。
# 最後の 1 つは、上の分割（学習 2018〜2023、検証 2024）と同じ。
ROLLING_FOLDS: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {
    "validation_2023": ((2018, 2019, 2020, 2021, 2022), (2023,)),
    "validation_2024": (SPLIT_YEARS[TRAIN], SPLIT_YEARS[VALIDATION]),
}


def rows_in_years(observations: pd.DataFrame, years: tuple[int, ...]) -> pd.Series:
    """`time`（UTC）の年が `years` に入っている行が True。"""
    return _utc_year(observations).isin(years).rename("in_years")
