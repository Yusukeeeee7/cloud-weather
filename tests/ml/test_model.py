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


def test_model_version_has_expected_form() -> None:
    # docs/spec.md「5. /cloud-base」の例：`2026-10-xx-lgbm-v1`。
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-lgbm-v\d+", model.MODEL_VERSION)
