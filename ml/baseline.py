"""ベースライン（概算式）。docs/spec.md「9. ベースライン」。"""

import pandas as pd

from ml.features import dew_point_spread_c
from ml.target import CEILING_CAP_M

# 概算式 `125 × (気温 − 露点)` [m] の係数。
RULE_OF_THUMB_M_PER_C = 125.0


def rule_of_thumb_m(spread_c: pd.Series) -> pd.Series:
    """概算式 `125 × (気温 − 露点)` [m]。"""
    return (spread_c * RULE_OF_THUMB_M_PER_C).astype("float64")


def baseline_m(temperature_c: pd.Series, dew_point_c: pd.Series) -> pd.Series:
    """概算式の値を、目的変数と同じ範囲（0〜上限）に収めたもの。欠損は欠損のまま。"""
    estimate = rule_of_thumb_m(dew_point_spread_c(temperature_c, dew_point_c))
    return estimate.clip(lower=0.0, upper=CEILING_CAP_M).rename("baseline_m")
