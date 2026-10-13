"""評価関数。docs/spec.md「9. 分割と評価」。"""

from collections.abc import Iterator
from typing import Any

import pandas as pd

from ml.features import season
from ml.target import CEILING_CAP_M

Metrics = dict[str, int | float | None]
METRICS = (
    "n",
    "mae_m",
    "n_below_cap",
    "mae_below_cap_m",
    "below_predicted_below",
    "below_predicted_cap",
    "cap_predicted_below",
    "cap_predicted_cap",
    "below_cap_accuracy",
)
# `report` の小数の桁数（再実行で差分が出ないように丸める）。
_REPORT_DIGITS = 2


def _evaluated(target_m: pd.Series, predicted_m: pd.Series) -> tuple[pd.Series, pd.Series]:
    """正解のある行だけの（正解, 予測）。その行の予測が欠損なら ValueError。"""
    if not target_m.index.equals(predicted_m.index):
        raise ValueError("target and prediction must have the same index")
    rows = target_m.notna().to_numpy()
    target, predicted = target_m[rows], predicted_m[rows]
    if predicted.isna().any():
        raise ValueError("missing prediction for a row with a target")
    return target, predicted


def _mean(values: pd.Series) -> float | None:
    return None if values.empty else float(values.mean())


def mae(target_m: pd.Series, predicted_m: pd.Series) -> float | None:
    """MAE（m）。正解のない行は数えない。行が 0 なら None。"""
    target, predicted = _evaluated(target_m, predicted_m)
    return _mean((predicted - target).abs())


def evaluate(target_m: pd.Series, predicted_m: pd.Series) -> Metrics:
    """全体の MAE、上限より下の行だけの MAE、「上限より下にあるか」の当たり外れ。

    「上限より下」は `< CEILING_CAP_M`。4 つの件数の名前は「正解_predicted_予測」。
    """
    target, predicted = _evaluated(target_m, predicted_m)
    error = (predicted - target).abs()
    below = target < CEILING_CAP_M
    predicted_below = predicted < CEILING_CAP_M
    return {
        "n": len(target),
        "mae_m": _mean(error),
        "n_below_cap": int(below.sum()),
        "mae_below_cap_m": _mean(error[below]),
        "below_predicted_below": int((below & predicted_below).sum()),
        "below_predicted_cap": int((below & ~predicted_below).sum()),
        "cap_predicted_below": int((~below & predicted_below).sum()),
        "cap_predicted_cap": int((~below & ~predicted_below).sum()),
        "below_cap_accuracy": _mean(below == predicted_below),
    }


def _by_group(
    target_m: pd.Series, predicted_m: pd.Series, keys: pd.DataFrame
) -> Iterator[tuple[tuple[Any, ...], Metrics]]:
    """`keys` の列の組ごとの（組の値, 指標）。組の順は値の順。"""
    if not keys.index.equals(target_m.index):
        raise ValueError("target and keys must have the same index")
    # 欠損のある組は groupby が黙って落とすので、先に止める。
    if keys.isna().any(axis=None):
        raise ValueError("missing key")
    _evaluated(target_m, predicted_m)
    target = target_m.reset_index(drop=True)
    predicted = predicted_m.reset_index(drop=True)
    for values, group in keys.reset_index(drop=True).groupby(list(keys.columns), sort=True):
        yield tuple(values), evaluate(target[group.index], predicted[group.index])


def evaluate_by(target_m: pd.Series, predicted_m: pd.Series, keys: pd.DataFrame) -> pd.DataFrame:
    """`keys` の列の組ごとに `evaluate` した表（1 行 ＝ 1 組。組の順は `keys` の値の順）。"""
    names = list(keys.columns)
    rows = [
        {**dict(zip(names, values, strict=True)), **metrics}
        for values, metrics in _by_group(target_m, predicted_m, keys)
    ]
    return pd.DataFrame(rows, columns=[*names, *METRICS])


def _rounded(metrics: Metrics) -> Metrics:
    return {
        name: round(value, _REPORT_DIGITS) if isinstance(value, float) else value
        for name, value in metrics.items()
    }


def report(
    observations: pd.DataFrame, target_m: pd.Series, predicted_m: pd.Series
) -> dict[str, Any]:
    """全体・都市別・都市 × 季節別の指標。JSON にできる（小数 2 桁、NaN なし）。"""
    keys = observations[["city"]].assign(season=season(observations))
    by_city = {
        str(city): _rounded(metrics)
        for (city,), metrics in _by_group(target_m, predicted_m, keys[["city"]])
    }
    by_city_season: dict[str, dict[str, Metrics]] = {}
    for (city, name), metrics in _by_group(target_m, predicted_m, keys):
        by_city_season.setdefault(str(city), {})[str(name)] = _rounded(metrics)
    return {
        "overall": _rounded(evaluate(target_m, predicted_m)),
        "by_city": by_city,
        "by_city_season": by_city_season,
    }
