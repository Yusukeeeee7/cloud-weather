import pandas as pd
import pytest

from ml import train
from ml.features import FEATURE_NAMES
from tests.ml.tables import feature_table, meters, step_training_table

# 手で作った表で変える列（ほかの列はすべて 0）。
VARYING = "dew_point_spread_c"


def _probe() -> pd.DataFrame:
    """小さい値（正解は低い）と大きい値（正解は上限）の 2 行。"""
    return feature_table(FEATURE_NAMES, VARYING, [1.0, 9.0])


def test_fit_learns_an_obvious_relation() -> None:
    features, target = step_training_table(FEATURE_NAMES, VARYING)

    booster = train.fit(features, target, features, target)
    low, high = booster.predict(_probe())

    # 値の期待値は作らない。向きだけを確かめる。
    assert low < high


def test_fit_is_reproducible() -> None:
    features, target = step_training_table(FEATURE_NAMES, VARYING)

    first = train.fit(features, target, features, target)
    second = train.fit(features, target, features, target)

    assert first.predict(features).tolist() == second.predict(features).tolist()
    assert first.best_iteration == second.best_iteration


def test_fit_uses_only_rows_with_target() -> None:
    features, target = step_training_table(FEATURE_NAMES, VARYING)
    # 正解のない行（学習・評価から除く行）を、学習と検証の両方に足す。
    extra = feature_table(FEATURE_NAMES, VARYING, [0.5] * 40)
    more_features = pd.concat([features, extra], ignore_index=True)
    more_target = pd.concat([target, meters(*[None] * 40)], ignore_index=True)

    expected = train.fit(features, target, features, target)
    actual = train.fit(more_features, more_target, more_features, more_target)

    assert actual.predict(features).tolist() == expected.predict(features).tolist()


def test_fit_rejects_empty_or_misaligned_input() -> None:
    features, target = step_training_table(FEATURE_NAMES, VARYING)
    no_target = meters(*[None] * len(target))
    shifted = target.set_axis(target.index + 1)
    other_columns = features.rename(columns={VARYING: "something_else"})
    reordered = features[list(reversed(FEATURE_NAMES))]

    # 正解のある行が 0（学習・検証のどちらでも）。
    with pytest.raises(ValueError):
        train.fit(features, no_target, features, target)
    with pytest.raises(ValueError):
        train.fit(features, target, features, no_target)
    # 特徴量と正解の行がずれている。
    with pytest.raises(ValueError):
        train.fit(features, shifted, features, target)
    with pytest.raises(ValueError):
        train.fit(features, target, features, shifted)
    # 列の名前・順が `FEATURE_NAMES` と違う。
    for wrong in (other_columns, reordered):
        with pytest.raises(ValueError):
            train.fit(wrong, target, features, target)
        with pytest.raises(ValueError):
            train.fit(features, target, wrong, target)


def test_fit_does_not_modify_input() -> None:
    features, target = step_training_table(FEATURE_NAMES, VARYING)
    target.iloc[0] = None
    before = (features.copy(deep=True), target.copy())

    train.fit(features, target, features, target)

    pd.testing.assert_frame_equal(features, before[0])
    pd.testing.assert_series_equal(target, before[1])


# ここから下は #17（docs/plans/17-model-improvement.md）。上限は 1,524 m。
CAP_M = 1524.0


def _mixed_table() -> tuple[pd.DataFrame, pd.Series]:
    """同じ特徴量に、上限の行と低い行が混ざった表。

    値 1 の 100 行は、60 行が上限・40 行が 300 m。値 9 の 100 行は、すべて上限。
    """
    features = feature_table(FEATURE_NAMES, VARYING, [1.0] * 100 + [9.0] * 100)
    return features, meters(*[CAP_M] * 60, *[300.0] * 40, *[CAP_M] * 100)


def _below_cap_table() -> tuple[pd.DataFrame, pd.Series]:
    """正解がすべて上限より下の表。値が 5 未満の行は 300 m、5 以上の行は 900 m。"""
    values = [row / 20 for row in range(200)]
    target = meters(*[300.0 if value < 5 else 900.0 for value in values])
    return feature_table(FEATURE_NAMES, VARYING, values), target


def test_fit_default_weight_gives_same_model() -> None:
    features, target = step_training_table(FEATURE_NAMES, VARYING)

    expected = train.fit(features, target, features, target)
    actual = train.fit(features, target, features, target, below_cap_weight=1.0)

    assert actual.model_to_string() == expected.model_to_string()
    assert actual.best_iteration == expected.best_iteration


def test_fit_below_cap_weight_lowers_predictions() -> None:
    features, target = _mixed_table()
    mixed = feature_table(FEATURE_NAMES, VARYING, [1.0])

    plain = train.fit(features, target, features, target)
    weighted = train.fit(features, target, features, target, below_cap_weight=8.0)

    # 値の期待値は作らない。重みを付けると、混ざった行の予測が低いほうに動く。
    assert weighted.predict(mixed)[0] < plain.predict(mixed)[0]


def test_fit_weights_the_validation_error_too() -> None:
    # 木の数を決める検証の MAE にも、同じ重みを付ける（計画「比べる設定」）。
    features, target = _mixed_table()
    weight = 4.0

    booster = train.fit(features, target, features, target, below_cap_weight=weight)

    error = (pd.Series(booster.predict(features)) - target).abs()
    weights = target.lt(CAP_M).map({True: weight, False: 1.0})
    weighted_mae = float((error * weights).sum() / weights.sum())
    # 重みで変わる表であること（そうでなければ、下の比較は何も確かめない）。
    assert weighted_mae != pytest.approx(float(error.mean()))
    assert booster.best_score["validation"]["l1"] == pytest.approx(weighted_mae)


@pytest.mark.parametrize("weight", [0.0, -1.0, float("nan"), float("inf")])
def test_fit_rejects_invalid_weight(weight: float) -> None:
    features, target = step_training_table(FEATURE_NAMES, VARYING)

    with pytest.raises(ValueError):
        train.fit(features, target, features, target, below_cap_weight=weight)


def test_fit_classifier_learns_an_obvious_relation() -> None:
    features, target = step_training_table(FEATURE_NAMES, VARYING)

    classifier = train.fit_classifier(features, target, features, target)
    low, high = classifier.predict(_probe())

    # 出すのは「上限より下」の確率。値が小さい行（正解は 300 m）のほうが大きい。
    assert 0.0 <= high < low <= 1.0


def test_fit_classifier_rejects_single_class_empty_or_misaligned() -> None:
    features, target = step_training_table(FEATURE_NAMES, VARYING)
    all_cap = meters(*[CAP_M] * len(target))
    all_below = meters(*[300.0] * len(target))
    no_target = meters(*[None] * len(target))
    shifted = target.set_axis(target.index + 1)
    reordered = features[list(reversed(FEATURE_NAMES))]

    # 学習の行が、すべて上限・すべて上限より下。
    for single in (all_cap, all_below):
        with pytest.raises(ValueError):
            train.fit_classifier(features, single, features, target)
    with pytest.raises(ValueError):
        train.fit_classifier(features, no_target, features, target)
    with pytest.raises(ValueError):
        train.fit_classifier(features, target, features, no_target)
    with pytest.raises(ValueError):
        train.fit_classifier(features, shifted, features, target)
    with pytest.raises(ValueError):
        train.fit_classifier(reordered, target, features, target)


def test_fit_below_cap_uses_only_rows_below_cap() -> None:
    features, target = _below_cap_table()
    # 上限の行と、正解のない行を、学習と検証の両方に足す。
    extra = feature_table(FEATURE_NAMES, VARYING, [0.5] * 80)
    more_features = pd.concat([features, extra], ignore_index=True)
    more_target = pd.concat([target, meters(*[CAP_M] * 40, *[None] * 40)], ignore_index=True)

    expected = train.fit(features, target, features, target)
    actual = train.fit_below_cap(more_features, more_target, more_features, more_target)

    assert actual.predict(features).tolist() == expected.predict(features).tolist()
    assert actual.best_iteration == expected.best_iteration


def test_fit_below_cap_rejects_no_rows_below_cap() -> None:
    features, target = _below_cap_table()
    all_cap = meters(*[CAP_M] * len(target))

    with pytest.raises(ValueError):
        train.fit_below_cap(features, all_cap, features, target)
    with pytest.raises(ValueError):
        train.fit_below_cap(features, target, features, all_cap)


def test_new_fits_are_reproducible_and_do_not_modify_input() -> None:
    features, target = _mixed_table()
    target.iloc[0] = None
    before = (features.copy(deep=True), target.copy())

    for fit in (
        lambda: train.fit(features, target, features, target, below_cap_weight=4.0),
        lambda: train.fit_classifier(features, target, features, target),
        lambda: train.fit_below_cap(features, target, features, target),
    ):
        first, second = fit(), fit()

        assert first.predict(features).tolist() == second.predict(features).tolist()
        assert first.best_iteration == second.best_iteration
    pd.testing.assert_frame_equal(features, before[0])
    pd.testing.assert_series_equal(target, before[1])
