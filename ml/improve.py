"""モデルの改善（#17）で比べる設定と、選ぶ決まり。docs/plans/17-model-improvement.md。"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import lightgbm as lgb
import pandas as pd

from ml import train
from ml.model import MODEL_VERSION_V1, MODEL_VERSION_V2, CloudBaseModel

# 設定 → 検証の年の名前 → 都市 → `evaluate.success_criteria` の結果。
Criteria = Mapping[str, Mapping[str, Mapping[str, Mapping[str, Any]]]]


@dataclass(frozen=True)
class Setting:
    name: str
    kind: Literal["current", "weighted", "two_stage"]
    # 正解が上限より下の行の重み（`weighted` だけ）。
    below_cap_weight: float | None = None
    # 「上限より下」と答える確率の閾値（`two_stage` だけ）。
    below_cap_threshold: float | None = None


# v1 と同じ設定。比べる相手で、選ぶ対象にしない。
REFERENCE = "current"
# 順は、点が同じときに選ぶ順（上のものを選ぶ）。
SETTINGS: tuple[Setting, ...] = (
    Setting(REFERENCE, "current"),
    Setting("weighted_2", "weighted", below_cap_weight=2.0),
    Setting("weighted_4", "weighted", below_cap_weight=4.0),
    Setting("weighted_8", "weighted", below_cap_weight=8.0),
    Setting("two_stage_50", "two_stage", below_cap_threshold=0.5),
    Setting("two_stage_40", "two_stage", below_cap_threshold=0.4),
    Setting("two_stage_30", "two_stage", below_cap_threshold=0.3),
)
SELECTABLE: tuple[str, ...] = tuple(
    setting.name for setting in SETTINGS if setting.name != REFERENCE
)


def fit_candidates(
    train_features: pd.DataFrame,
    train_target_m: pd.Series,
    validation_features: pd.DataFrame,
    validation_target_m: pd.Series,
    train_years: tuple[int, ...],
) -> dict[str, CloudBaseModel]:
    """設定ごとのモデル（`SETTINGS` の順）。`two_stage` の 3 つは、同じ 2 つのモデルを使う。"""
    data = (train_features, train_target_m, validation_features, validation_target_m)
    stages: tuple[lgb.Booster, lgb.Booster] | None = None
    candidates: dict[str, CloudBaseModel] = {}
    for setting in SETTINGS:
        if setting.kind == "current":
            candidates[setting.name] = CloudBaseModel(
                booster=train.fit(*data), train_years=train_years, model_version=MODEL_VERSION_V1
            )
        elif setting.below_cap_weight is not None:
            candidates[setting.name] = CloudBaseModel(
                booster=train.fit(*data, below_cap_weight=setting.below_cap_weight),
                train_years=train_years,
                model_version=MODEL_VERSION_V2,
            )
        else:
            if stages is None:
                stages = (train.fit_below_cap(*data), train.fit_classifier(*data))
            candidates[setting.name] = CloudBaseModel(
                booster=stages[0],
                train_years=train_years,
                model_version=MODEL_VERSION_V2,
                classifier=stages[1],
                below_cap_threshold=setting.below_cap_threshold,
            )
    return candidates


def _judgements(criteria: Criteria) -> dict[str, list[Mapping[str, Any]]]:
    """設定ごとの、すべての検証の年 × 都市の判定。そろっていなければ ValueError。"""
    names = [setting.name for setting in SETTINGS]
    if set(criteria) != set(names):
        raise ValueError("criteria must have every setting and no others")
    folds = set(criteria[REFERENCE])
    cities = {city for by_city in criteria[REFERENCE].values() for city in by_city}
    if not folds or not cities:
        raise ValueError("criteria must have at least one fold and one city")
    judgements: dict[str, list[Mapping[str, Any]]] = {}
    for name in names:
        if set(criteria[name]) != folds:
            raise ValueError("every setting must have the same folds")
        if any(set(by_city) != cities for by_city in criteria[name].values()):
            raise ValueError("every fold must have the same cities")
        judgements[name] = [
            judged for by_city in criteria[name].values() for judged in by_city.values()
        ]
    return judgements


def select(criteria: Criteria) -> dict[str, Any]:
    """選ぶ決まり。`selection` は設定ごとの（残るか, 点）、`selected` は選んだ設定の名前。

    1. 残す：すべての検証の年 × 都市で、基準 1 を満たす（判定できないものは満たさない）。
    2. 点：基準 2 の改善の割合のうち、最も小さい値。
    3. 残った中で点が最も大きいものを選ぶ。同じなら `SETTINGS` の上のもの。
    4. その点が `current` の点より大きくなければ、選ばない（`selected` は None）。
    """
    selection: dict[str, dict[str, Any]] = {}
    for name, judged in _judgements(criteria).items():
        improvements = [item["mae_below_cap_improvement"] for item in judged]
        score = None if any(value is None for value in improvements) else min(improvements)
        eligible = score is not None and all(item["meets_mae"] is True for item in judged)
        selection[name] = {"eligible": eligible, "score": score}
    selected: str | None = None
    for name in SELECTABLE:
        if not selection[name]["eligible"]:
            continue
        if selected is None or selection[name]["score"] > selection[selected]["score"]:
            selected = name
    reference = selection[REFERENCE]["score"]
    if selected is not None and (reference is None or selection[selected]["score"] <= reference):
        selected = None
    return {"selection": selection, "selected": selected}


def adopt(test_criteria: Mapping[str, Mapping[str, Any]]) -> bool:
    """採る条件：テストの年で、すべての都市が成功基準の 1・2 を両方満たす。"""
    if not test_criteria:
        raise ValueError("criteria must have at least one city")
    return all(judged["meets_both"] is True for judged in test_criteria.values())
