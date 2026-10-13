"""誤差の分析（機能 #16）。docs/spec.md「9. モデルの改善」。

見るのは、正解が上限より下の行（`target_m < CEILING_CAP_M`）だけ。
符号は `予測 − 正解`（正なら高すぎ）。
"""

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pandas as pd

from ml.features import SEASONS, local_hour, season
from ml.target import CEILING_CAP_M

Summary = dict[str, int | float | None]
# 正解の高さの帯。境目は下の帯に入れる（300 m ちょうどは `0_300`）。docs/eda.md 3 節と同じ区切り。
HEIGHT_BANDS = ("0_300", "300_600", "600_1000", "1000_1524")
_BAND_EDGES_M = (float("-inf"), 300.0, 600.0, 1000.0, CEILING_CAP_M)
# 誤差の向き。`at_cap` は、予測が上限（＝ 低い天井を見逃した）。
DIRECTIONS = ("at_cap", "too_high", "too_low", "exact")
# 現地の時の帯：夜 0〜5、朝 6〜11、午後 12〜17、夕 18〜23。
HOUR_BANDS = ("night", "morning", "afternoon", "evening")
_HOURS_PER_BAND = 6
# 1 時間前の正解と比べた、正解の変化。
CHANGES = ("same", "lower", "higher", "unknown")
SUMMARY = (
    "n_below_cap",
    "mae_below_cap_m",
    "bias_below_cap_m",
    *(f"n_{name}" for name in DIRECTIONS),
    *(f"abs_error_{name}_m" for name in DIRECTIONS),
)
# `report` の小数の桁数（再実行で差分が出ないように丸める）。
_REPORT_DIGITS = 2


def _check(target_m: pd.Series, predicted_m: pd.Series) -> None:
    """行がそろっていて、正解のある行に予測があること。なければ ValueError。"""
    if not target_m.index.equals(predicted_m.index):
        raise ValueError("target and prediction must have the same index")
    if predicted_m[target_m.notna().to_numpy()].isna().any():
        raise ValueError("missing prediction for a row with a target")


def _mean(values: pd.Series) -> float | None:
    return None if values.empty else float(values.mean())


def height_band(target_m: pd.Series) -> pd.Series:
    """正解の高さの帯の名前（`HEIGHT_BANDS`）。上限の行・正解のない行は欠損。"""
    below_cap = target_m.where(target_m < CEILING_CAP_M)
    bands = pd.cut(below_cap, bins=list(_BAND_EDGES_M), labels=list(HEIGHT_BANDS), right=True)
    return bands.astype("object").rename("height_band")


def direction(target_m: pd.Series, predicted_m: pd.Series) -> pd.Series:
    """行ごとの誤差の向き（`DIRECTIONS`）。上限の行・正解のない行は欠損。"""
    _check(target_m, predicted_m)
    error = predicted_m - target_m
    names = pd.Series("exact", index=target_m.index, dtype="object")
    names[(error > 0).to_numpy()] = "too_high"
    names[(error < 0).to_numpy()] = "too_low"
    names[(predicted_m >= CEILING_CAP_M).to_numpy()] = "at_cap"
    return names.where(target_m < CEILING_CAP_M).rename("direction")


def summarize(target_m: pd.Series, predicted_m: pd.Series) -> Summary:
    """上限より下の行の、行数・MAE・偏り（`予測 − 正解` の平均）と、向きごとの行数・誤差の合計。

    誤差の合計は絶対値の合計（向きごとの合計を足すと、MAE × 行数になる）。
    """
    names = direction(target_m, predicted_m)
    rows = names.notna().to_numpy()
    names = names[rows]
    error = (predicted_m - target_m)[rows]
    absolute = error.abs()
    result: Summary = {
        "n_below_cap": len(error),
        "mae_below_cap_m": _mean(absolute),
        "bias_below_cap_m": _mean(error),
    }
    for name in DIRECTIONS:
        result[f"n_{name}"] = int((names == name).sum())
    for name in DIRECTIONS:
        result[f"abs_error_{name}_m"] = float(absolute[(names == name).to_numpy()].sum())
    return result


def _by_group(
    target_m: pd.Series, predicted_m: pd.Series, keys: pd.DataFrame
) -> Iterator[tuple[tuple[Any, ...], Summary]]:
    """`keys` の列の組ごとの（組の値, 集計）。組の順は値の順。"""
    if not keys.index.equals(target_m.index):
        raise ValueError("target and keys must have the same index")
    # 欠損のある組は groupby が黙って落とすので、先に止める。
    if keys.isna().any(axis=None):
        raise ValueError("missing key")
    _check(target_m, predicted_m)
    target = target_m.reset_index(drop=True)
    predicted = predicted_m.reset_index(drop=True)
    for values, group in keys.reset_index(drop=True).groupby(list(keys.columns), sort=True):
        yield tuple(values), summarize(target[group.index], predicted[group.index])


def summarize_by(target_m: pd.Series, predicted_m: pd.Series, keys: pd.DataFrame) -> pd.DataFrame:
    """`keys` の列の組ごとに `summarize` した表（1 行 ＝ 1 組。組の順は `keys` の値の順）。"""
    names = list(keys.columns)
    rows = [
        {**dict(zip(names, values, strict=True)), **summary}
        for values, summary in _by_group(target_m, predicted_m, keys)
    ]
    return pd.DataFrame(rows, columns=[*names, *SUMMARY])


def ceiling_change(observations: pd.DataFrame, target_m: pd.Series) -> pd.Series:
    """同じ都市の 1 時間前の正解と比べた変化（`CHANGES`）。

    1 時間前の行がない・どちらかの正解がない行は `unknown`。上限の行も正解として比べる。
    同じ都市・同じ時刻の行が 2 つあれば ValueError。
    分析のためだけの値（正解から作るので、特徴量にはできない）。
    """
    if not observations.index.equals(target_m.index):
        raise ValueError("observations and target must have the same index")
    city, time = observations["city"], observations["time"]
    if observations.duplicated(["city", "time"]).any():
        raise ValueError("duplicate city and time")
    by_hour = pd.Series(target_m.to_numpy(), index=pd.MultiIndex.from_arrays([city, time]))
    hour_before = pd.MultiIndex.from_arrays([city, time - pd.Timedelta(hours=1)])
    difference = target_m.to_numpy() - by_hour.reindex(hour_before).to_numpy()
    names = pd.Series("unknown", index=target_m.index, dtype="object")
    names[difference == 0] = "same"
    names[difference < 0] = "lower"
    names[difference > 0] = "higher"
    return names.rename("ceiling_change")


def _hour_band(observations: pd.DataFrame) -> pd.Series:
    """現地の時の帯（`HOUR_BANDS`）。"""
    return local_hour(observations).map(lambda hour: HOUR_BANDS[hour // _HOURS_PER_BAND])


def _rounded(summary: Summary) -> Summary:
    return {
        name: round(value, _REPORT_DIGITS) if isinstance(value, float) else value
        for name, value in summary.items()
    }


def _nested(
    target_m: pd.Series,
    predicted_m: pd.Series,
    keys: pd.DataFrame,
    levels: Sequence[Sequence[str]],
) -> Any:
    """`keys` の列の順に入れ子にした集計。`levels` の値の組は、行がなくても行数 0 で入れる。"""
    found = dict(_by_group(target_m, predicted_m, keys))
    empty = summarize(target_m.iloc[:0], predicted_m.iloc[:0])

    def build(group: tuple[str, ...], rest: Sequence[Sequence[str]]) -> Any:
        if not rest:
            return _rounded(found.get(group, empty))
        return {value: build((*group, value), rest[1:]) for value in rest[0]}

    return build((), levels)


def report(
    observations: pd.DataFrame, target_m: pd.Series, predictions: Mapping[str, pd.Series]
) -> dict[str, Any]:
    """予測の名前ごとの、上限より下の行の誤差の集計。JSON にできる（小数 2 桁、NaN なし）。

    分け方：全体、都市、都市 × 帯、都市 × 季節、都市 × 季節 × 帯、都市 × 現地の時の帯、
    都市 × 1 時間前からの正解の変化。
    """
    keys = pd.DataFrame(
        {
            "city": observations["city"].astype("str"),
            "band": height_band(target_m),
            "season": season(observations),
            "hour_band": _hour_band(observations),
            "change": ceiling_change(observations, target_m),
        }
    )
    cities = sorted(keys["city"].unique())
    rows = (target_m < CEILING_CAP_M).to_numpy()
    keys, target = keys[rows], target_m[rows]
    groupings: dict[str, tuple[list[str], list[Sequence[str]]]] = {
        "by_city": (["city"], [cities]),
        "by_city_band": (["city", "band"], [cities, HEIGHT_BANDS]),
        "by_city_season": (["city", "season"], [cities, SEASONS]),
        "by_city_season_band": (["city", "season", "band"], [cities, SEASONS, HEIGHT_BANDS]),
        "by_city_hour_band": (["city", "hour_band"], [cities, HOUR_BANDS]),
        "by_city_change": (["city", "change"], [cities, CHANGES]),
    }
    result: dict[str, Any] = {}
    for name, predicted_m in predictions.items():
        _check(target_m, predicted_m)
        predicted = predicted_m[rows]
        part: dict[str, Any] = {"overall": _rounded(summarize(target, predicted))}
        for grouping, (columns, levels) in groupings.items():
            part[grouping] = _nested(target, predicted, keys[columns], levels)
        result[name] = part
    return result
