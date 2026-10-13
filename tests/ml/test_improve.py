import copy
from typing import Any

import pandas as pd
import pytest

from ml import improve, model, split, train
from ml.features import FEATURE_NAMES
from tests.ml.tables import feature_table

# docs/spec.md「9. 目的変数」：上限は 1,524 m。
CAP_M = 1524.0
VARYING = "dew_point_spread_c"
FOLDS = tuple(split.ROLLING_FOLDS)
CITIES = ("berlin", "tokyo")
# docs/plans/17-model-improvement.md「比べる設定」の表の順。
SELECTABLE = (
    "weighted_2",
    "weighted_4",
    "weighted_8",
    "two_stage_50",
    "two_stage_40",
    "two_stage_30",
)


def _training_table() -> tuple[pd.DataFrame, pd.Series]:
    """値が 2.5 未満は 300 m、5 未満は 900 m、5 以上は上限（1,524 m）の表。200 行。"""
    values = [row / 20 for row in range(200)]
    target = pd.Series(
        [300.0 if value < 2.5 else 900.0 if value < 5 else CAP_M for value in values],
        dtype="float64",
    )
    return feature_table(FEATURE_NAMES, VARYING, values), target


def _judged(meets_mae: bool | None = True, below: float | None = 0.2) -> dict[str, Any]:
    """`evaluate.success_criteria` と同じ形の、手で書いた判定。"""
    meets_below = None if below is None else below >= 0.1
    judged = meets_mae is not None and meets_below is not None
    return {
        "mae_improvement": None if meets_mae is None else (0.3 if meets_mae else 0.05),
        "meets_mae": meets_mae,
        "mae_below_cap_improvement": below,
        "meets_mae_below_cap": meets_below,
        "meets_both": (meets_mae and meets_below) if judged else None,
    }


def _criteria(scores: dict[str, float], current: float = -0.1) -> dict[str, Any]:
    """すべての設定・検証の年・都市が基準 1 を満たす表。改善 2 は設定ごとに `scores` の値。

    `scores` にない設定は、`current` と同じ値（選ばれない）。
    """
    names = [setting.name for setting in improve.SETTINGS]
    return {
        name: {
            fold: {city: _judged(below=scores.get(name, current)) for city in CITIES}
            for fold in FOLDS
        }
        for name in names
    }


def test_settings_follow_plan() -> None:
    settings = {setting.name: setting for setting in improve.SETTINGS}

    assert list(settings) == ["current", *SELECTABLE]
    assert improve.REFERENCE == "current"
    assert improve.SELECTABLE == SELECTABLE
    assert (settings["current"].kind, settings["current"].below_cap_weight) == ("current", None)
    assert settings["current"].below_cap_threshold is None
    for name, weight in (("weighted_2", 2.0), ("weighted_4", 4.0), ("weighted_8", 8.0)):
        assert settings[name].kind == "weighted"
        assert settings[name].below_cap_weight == weight
        assert settings[name].below_cap_threshold is None
    for name, threshold in (("two_stage_50", 0.5), ("two_stage_40", 0.4), ("two_stage_30", 0.3)):
        assert settings[name].kind == "two_stage"
        assert settings[name].below_cap_weight is None
        assert settings[name].below_cap_threshold == threshold


def test_fit_candidates_returns_a_model_for_each_setting() -> None:
    features, target = _training_table()

    candidates = improve.fit_candidates(features, target, features, target, (2018, 2019))

    assert list(candidates) == ["current", *SELECTABLE]
    for candidate in candidates.values():
        assert candidate.train_years == (2018, 2019)
        assert model.predict_m(candidate, features).between(0.0, CAP_M).all()
    # `current` は、v1 と同じ学習。
    current = candidates["current"]
    expected = train.fit(features, target, features, target)
    assert current.classifier is None
    assert current.model_version == model.MODEL_VERSION_V1
    assert current.booster.predict(features).tolist() == expected.predict(features).tolist()
    for name in ("weighted_2", "weighted_4", "weighted_8"):
        assert candidates[name].classifier is None
        assert candidates[name].model_version == model.MODEL_VERSION_V2
    # 閾値の 3 つは、同じ 2 つのモデルで、閾値だけが違う。
    two_stage = [candidates[name] for name in ("two_stage_50", "two_stage_40", "two_stage_30")]
    assert [candidate.below_cap_threshold for candidate in two_stage] == [0.5, 0.4, 0.3]
    for candidate in two_stage:
        assert candidate.model_version == model.MODEL_VERSION_V2
        assert candidate.classifier is two_stage[0].classifier is not None
        assert candidate.booster is two_stage[0].booster


def test_select_requires_criterion_1_in_every_city_and_fold() -> None:
    criteria = _criteria({"weighted_2": 0.5, "two_stage_50": 0.3})
    # 点が最も大きい設定が、4 つのうち 1 つだけ基準 1 を満たさない。
    criteria["weighted_2"][FOLDS[0]]["tokyo"] = _judged(meets_mae=False, below=0.5)

    result = improve.select(criteria)

    assert result["selection"]["weighted_2"] == {"eligible": False, "score": 0.5}
    assert result["selection"]["two_stage_50"]["eligible"] is True
    assert result["selected"] == "two_stage_50"


def test_select_score_is_smallest_criterion_2_improvement() -> None:
    criteria = _criteria({"weighted_4": 0.4})
    criteria["weighted_4"][FOLDS[0]]["berlin"] = _judged(below=0.25)
    criteria["weighted_4"][FOLDS[1]]["tokyo"] = _judged(below=0.15)

    result = improve.select(criteria)

    assert result["selection"]["weighted_4"] == {"eligible": True, "score": 0.15}
    assert result["selection"]["current"] == {"eligible": True, "score": -0.1}


def test_select_picks_highest_score_among_eligible() -> None:
    criteria = _criteria({"weighted_2": 0.12, "two_stage_40": 0.3, "two_stage_30": 0.2})

    assert improve.select(criteria)["selected"] == "two_stage_40"


def test_select_tie_goes_to_earlier_setting() -> None:
    criteria = _criteria({"two_stage_30": 0.2, "weighted_8": 0.2, "two_stage_50": 0.2})

    assert improve.select(criteria)["selected"] == "weighted_8"


def test_select_none_unless_better_than_current() -> None:
    # `current` と同じ・小さい。
    assert improve.select(_criteria({"weighted_2": -0.1, "weighted_4": -0.3}))["selected"] is None
    # ほんの少しでも大きければ選ぶ。
    assert improve.select(_criteria({"weighted_2": -0.09}))["selected"] == "weighted_2"
    # 残った設定がない。
    criteria = _criteria({"weighted_2": 0.5})
    for name in SELECTABLE:
        criteria[name][FOLDS[1]]["berlin"] = _judged(meets_mae=False, below=0.5)
    result = improve.select(criteria)
    assert result["selected"] is None
    assert not any(result["selection"][name]["eligible"] for name in SELECTABLE)


def test_select_treats_unjudged_as_not_eligible() -> None:
    # 上限より下の行がない都市は、基準 2 を判定できない（サンプルの東京）。
    criteria = _criteria({"weighted_2": 0.5, "weighted_4": 0.3})
    criteria["weighted_2"][FOLDS[0]]["tokyo"] = _judged(below=None)
    criteria["weighted_4"][FOLDS[0]]["tokyo"] = _judged(meets_mae=None, below=0.3)

    result = improve.select(criteria)

    assert result["selection"]["weighted_2"] == {"eligible": False, "score": None}
    assert result["selection"]["weighted_4"]["eligible"] is False
    assert result["selected"] is None
    # `current` を判定できなければ、「`current` より良い」と言えないので選ばない。
    criteria = _criteria({"weighted_2": 0.5})
    criteria["current"][FOLDS[0]]["tokyo"] = _judged(below=None)
    assert improve.select(criteria)["selected"] is None


def test_select_rejects_missing_setting_fold_or_city() -> None:
    no_setting = _criteria({})
    del no_setting["weighted_8"]
    unknown_setting = _criteria({})
    unknown_setting["something_else"] = unknown_setting["current"]
    no_fold = _criteria({})
    del no_fold["two_stage_50"][FOLDS[0]]
    no_city = _criteria({})
    del no_city["two_stage_50"][FOLDS[1]]["tokyo"]
    no_folds_at_all: dict[str, Any] = {name: {} for name in _criteria({})}

    for wrong in (no_setting, unknown_setting, no_fold, no_city, no_folds_at_all):
        with pytest.raises(ValueError):
            improve.select(wrong)


def test_adopt_requires_both_criteria_in_every_city() -> None:
    meets = _judged(below=0.1)
    fails_below = _judged(below=0.09)
    fails_overall = _judged(meets_mae=False, below=0.5)
    unjudged = _judged(below=None)

    assert improve.adopt({"berlin": meets, "tokyo": meets}) is True
    for other in (fails_below, fails_overall, unjudged):
        assert improve.adopt({"berlin": meets, "tokyo": other}) is False
        assert improve.adopt({"berlin": other, "tokyo": meets}) is False
    with pytest.raises(ValueError):
        improve.adopt({})


def test_improve_does_not_modify_input() -> None:
    features, target = _training_table()
    target.iloc[0] = None
    before = (features.copy(deep=True), target.copy())
    criteria = _criteria({"weighted_2": 0.2})
    criteria_before = copy.deepcopy(criteria)
    by_city = {"berlin": _judged(), "tokyo": _judged()}
    by_city_before = copy.deepcopy(by_city)

    improve.fit_candidates(features, target, features, target, (2018,))
    improve.select(criteria)
    improve.adopt(by_city)

    pd.testing.assert_frame_equal(features, before[0])
    pd.testing.assert_series_equal(target, before[1])
    assert criteria == criteria_before
    assert by_city == by_city_before
