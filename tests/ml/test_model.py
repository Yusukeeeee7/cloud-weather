import re
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
import pytest

from ml import model, train
from ml.features import FEATURE_NAMES
from tests.ml.tables import feature_table, step_training_table

# docs/spec.md「9. 目的変数」：上限は 1,524 m。
CAP_M = 1524.0
VARYING = "dew_point_spread_c"


class _FakeBooster:
    """決まった値を返す、モデルの代わり。"""

    def __init__(self, *values: float) -> None:
        self.values = values

    def predict(self, data: Any, **_: Any) -> Any:
        return pd.Series(self.values, dtype="float64").to_numpy()


def _fake_model(*values: float) -> model.CloudBaseModel:
    return model.CloudBaseModel(booster=_FakeBooster(*values), train_years=(2018,))  # type: ignore[arg-type]


def _fitted_model() -> tuple[model.CloudBaseModel, pd.DataFrame]:
    features, target = step_training_table(FEATURE_NAMES, VARYING)
    booster = train.fit(features, target, features, target)
    return model.CloudBaseModel(booster=booster, train_years=(2018, 2019)), features


def test_predict_is_within_zero_and_cap() -> None:
    features = feature_table(FEATURE_NAMES, VARYING, [0.0, 1.0, 2.0, 3.0, 4.0])

    predicted = model.predict_m(_fake_model(-50.0, 0.0, 700.5, CAP_M, 99999.0), features)

    assert predicted.tolist() == [0.0, 0.0, 700.5, CAP_M, CAP_M]


def test_predict_keeps_index_and_name() -> None:
    features = feature_table(FEATURE_NAMES, VARYING, [0.0, 1.0, 2.0])
    features.index = pd.Index([9, 4, 2])

    predicted = model.predict_m(_fake_model(100.0, 200.0, 300.0), features)

    assert list(predicted.index) == [9, 4, 2]
    assert predicted.name == "predicted_m"
    assert predicted.dtype == "float64"
    assert predicted.tolist() == [100.0, 200.0, 300.0]


def test_predict_rejects_wrong_feature_columns() -> None:
    features = feature_table(FEATURE_NAMES, VARYING, [0.0])
    missing = features.drop(columns=[VARYING])
    extra = features.assign(visibility_m=10000.0)
    # LightGBM は列の名前を見ないので、順が違うと別の列として読んでしまう。
    reordered = features[list(reversed(FEATURE_NAMES))]

    for wrong in (missing, extra, reordered):
        with pytest.raises(ValueError):
            model.predict_m(_fake_model(100.0), wrong)


def test_predict_uses_the_fitted_model() -> None:
    fitted, features = _fitted_model()

    predicted = model.predict_m(fitted, features)

    assert predicted.between(0.0, CAP_M).all()
    # 手で作った表：値が小さい行は低く、大きい行は高い。
    assert predicted.iloc[0] < predicted.iloc[-1]


def test_save_and_load_give_same_predictions(tmp_path: Path) -> None:
    fitted, features = _fitted_model()
    path = tmp_path / "cloud_base.joblib"

    model.save(fitted, path)
    loaded = model.load(path)

    pd.testing.assert_series_equal(
        model.predict_m(loaded, features), model.predict_m(fitted, features)
    )
    assert loaded.model_version == model.MODEL_VERSION
    assert loaded.feature_names == FEATURE_NAMES
    assert loaded.cap_m == CAP_M
    assert loaded.train_years == (2018, 2019)


def test_load_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(model.ModelLoadError):
        model.load(tmp_path / "cloud_base.joblib")


def test_load_rejects_unexpected_content(tmp_path: Path) -> None:
    fitted, _ = _fitted_model()
    garbage = tmp_path / "garbage.joblib"
    garbage.write_bytes(b"not a model")
    other_object = tmp_path / "other.joblib"
    joblib.dump([1, 2, 3], other_object)
    # いまのコードと違う特徴量で作ったモデル。
    other_features = tmp_path / "other_features.joblib"
    stale = model.CloudBaseModel(
        booster=fitted.booster, train_years=(2018,), feature_names=("temperature_c",)
    )
    model.save(stale, other_features)
    # 項目はそろっているが、モデルの本体が LightGBM のモデルでない。
    other_booster = tmp_path / "other_booster.joblib"
    joblib.dump(
        {
            "booster": "not a booster",
            "train_years": [2018],
            "feature_names": list(FEATURE_NAMES),
            "model_version": model.MODEL_VERSION,
            "cap_m": CAP_M,
        },
        other_booster,
    )

    for path in (garbage, other_object, other_features, other_booster):
        with pytest.raises(model.ModelLoadError):
            model.load(path)


def test_model_versions_have_expected_form() -> None:
    # docs/spec.md「5. /cloud-base」の例：`2026-10-xx-lgbm-v1`。v1 の値は spec「9. 特徴量」。
    assert model.MODEL_VERSION_V1 == "2026-10-13-lgbm-v1"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-lgbm-v2", model.MODEL_VERSION_V2)
    assert model.MODEL_VERSION in (model.MODEL_VERSION_V1, model.MODEL_VERSION_V2)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-lgbm-v\d+", model.MODEL_VERSION)


# ここから下は #17（docs/plans/17-model-improvement.md）の 2 段階のモデル。
TWO_STAGE_KEYS = {"classifier", "below_cap_threshold"}


def _fake_two_stage(
    values: tuple[float, ...], probabilities: tuple[float, ...], threshold: float = 0.5
) -> model.CloudBaseModel:
    return model.CloudBaseModel(
        booster=_FakeBooster(*values),  # type: ignore[arg-type]
        train_years=(2018,),
        classifier=_FakeBooster(*probabilities),  # type: ignore[arg-type]
        below_cap_threshold=threshold,
    )


def _fitted_two_stage() -> tuple[model.CloudBaseModel, pd.DataFrame]:
    """値が 2.5 未満は 300 m、5 未満は 900 m、5 以上は上限の表で学習した 2 段階のモデル。"""
    values = [row / 20 for row in range(200)]
    features = feature_table(FEATURE_NAMES, VARYING, values)
    target = pd.Series(
        [300.0 if value < 2.5 else 900.0 if value < 5 else CAP_M for value in values],
        dtype="float64",
    )
    fitted = model.CloudBaseModel(
        booster=train.fit_below_cap(features, target, features, target),
        train_years=(2018, 2019),
        classifier=train.fit_classifier(features, target, features, target),
        below_cap_threshold=0.4,
    )
    return fitted, features


def test_predict_two_stage_uses_cap_below_threshold() -> None:
    features = feature_table(FEATURE_NAMES, VARYING, [0.0, 1.0, 2.0])
    two_stage = _fake_two_stage((200.0, 300.0, 400.0), (0.49, 0.5, 0.51), threshold=0.5)

    predicted = model.predict_m(two_stage, features)

    # 確率が閾値より小さければ上限。閾値ちょうど・大きければ回帰の値。
    assert predicted.tolist() == [CAP_M, 300.0, 400.0]


def test_predict_two_stage_is_within_zero_and_cap() -> None:
    features = feature_table(FEATURE_NAMES, VARYING, [0.0, 1.0, 2.0])
    features.index = pd.Index([9, 4, 2])
    two_stage = _fake_two_stage((-50.0, 99999.0, 700.5), (1.0, 1.0, 1.0))

    predicted = model.predict_m(two_stage, features)

    assert predicted.tolist() == [0.0, CAP_M, 700.5]
    assert list(predicted.index) == [9, 4, 2]
    assert predicted.name == "predicted_m"
    assert predicted.dtype == "float64"
    with pytest.raises(ValueError):
        model.predict_m(two_stage, features[list(reversed(FEATURE_NAMES))])


def test_two_stage_requires_classifier_and_threshold_together() -> None:
    booster: Any = _FakeBooster(100.0)

    with pytest.raises(ValueError):
        model.CloudBaseModel(booster=booster, train_years=(2018,), classifier=booster)
    with pytest.raises(ValueError):
        model.CloudBaseModel(booster=booster, train_years=(2018,), below_cap_threshold=0.5)
    for threshold in (0.0, 1.0, -0.1, 1.5, float("nan")):
        with pytest.raises(ValueError):
            model.CloudBaseModel(
                booster=booster,
                train_years=(2018,),
                classifier=booster,
                below_cap_threshold=threshold,
            )


def test_save_and_load_two_stage_give_same_predictions(tmp_path: Path) -> None:
    fitted, features = _fitted_two_stage()
    path = tmp_path / "cloud_base.joblib"

    model.save(fitted, path)
    loaded = model.load(path)

    pd.testing.assert_series_equal(
        model.predict_m(loaded, features), model.predict_m(fitted, features)
    )
    assert loaded.below_cap_threshold == 0.4
    assert loaded.classifier is not None
    assert loaded.train_years == (2018, 2019)
    # 手で作った表：低い行は上限より下、上限の行は上限と答える。
    predicted = model.predict_m(loaded, features)
    assert predicted.iloc[0] < CAP_M
    assert predicted.iloc[-1] == CAP_M


def test_save_one_stage_keeps_five_keys(tmp_path: Path) -> None:
    fitted, _ = _fitted_model()
    path = tmp_path / "cloud_base.joblib"

    model.save(fitted, path)

    # v1 のファイルと同じ中身（2 段階のキーを足さない）。
    assert set(joblib.load(path)) == {
        "booster",
        "train_years",
        "feature_names",
        "model_version",
        "cap_m",
    }


def test_load_rejects_unexpected_two_stage_content(tmp_path: Path) -> None:
    fitted, _ = _fitted_two_stage()
    good = tmp_path / "good.joblib"
    model.save(fitted, good)
    content = joblib.load(good)
    assert TWO_STAGE_KEYS <= set(content)
    wrong_contents = [
        {**content, "classifier": "not a booster"},
        {**content, "below_cap_threshold": "0.5"},
        {**content, "below_cap_threshold": 1.5},
        {**content, "below_cap_threshold": None},
        {key: value for key, value in content.items() if key != "classifier"},
        {key: value for key, value in content.items() if key != "below_cap_threshold"},
        {**content, "something_else": 1},
    ]

    for number, wrong in enumerate(wrong_contents):
        path = tmp_path / f"wrong_{number}.joblib"
        joblib.dump(wrong, path)
        with pytest.raises(model.ModelLoadError):
            model.load(path)
