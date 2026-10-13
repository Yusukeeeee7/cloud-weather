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
