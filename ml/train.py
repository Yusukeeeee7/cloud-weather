"""学習の設定と学習。docs/spec.md「9. 雲底高度予測（ML）」。"""

import math
from typing import Any

import lightgbm as lgb
import pandas as pd

from ml.features import FEATURE_NAMES
from ml.target import CEILING_CAP_M

SEED = 0
# 設定は固定（探索しない）。目的関数は評価の指標と同じ MAE。
PARAMS: dict[str, Any] = {
    "objective": "regression_l1",
    "metric": "l1",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 20,
    "seed": SEED,
    # 再実行で同じ結果にする。
    "num_threads": 1,
    "deterministic": True,
    "force_row_wise": True,
    "verbose": -1,
}
# 「上限より下か」の分類（#17 の 2 段階のモデル）。目的関数と指標のほかは同じ。
CLASSIFIER_PARAMS: dict[str, Any] = {**PARAMS, "objective": "binary", "metric": "binary_logloss"}
# 木の数の上限と、検証の年の MAE が良くならないまま続けてよい回数。
MAX_ROUNDS = 2000
EARLY_STOPPING_ROUNDS = 50


def _rows_with_target(
    features: pd.DataFrame, target_m: pd.Series
) -> tuple[pd.DataFrame, pd.Series]:
    if list(features.columns) != list(FEATURE_NAMES):
        raise ValueError("features do not have the expected columns")
    if not features.index.equals(target_m.index):
        raise ValueError("features and target must have the same index")
    rows = target_m.notna().to_numpy()
    if not rows.any():
        raise ValueError("no rows with a target")
    return features[rows], target_m[rows]


def _below_cap(target_m: pd.Series) -> pd.Series:
    """正解が上限より下の行が True（正解のない行は False）。"""
    return target_m < CEILING_CAP_M


def _weights(target_m: pd.Series, below_cap_weight: float) -> pd.Series | None:
    """上限より下の行だけ `below_cap_weight`、ほかは 1。1 なら重みを付けない。"""
    if below_cap_weight == 1.0:
        return None
    return _below_cap(target_m).map({True: below_cap_weight, False: 1.0}).astype("float64")


def _train(params: dict[str, Any], train: lgb.Dataset, validation: lgb.Dataset) -> lgb.Booster:
    return lgb.train(
        dict(params),
        train,
        num_boost_round=MAX_ROUNDS,
        valid_sets=[validation],
        valid_names=["validation"],
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )


def fit(
    train_features: pd.DataFrame,
    train_target_m: pd.Series,
    validation_features: pd.DataFrame,
    validation_target_m: pd.Series,
    below_cap_weight: float = 1.0,
) -> lgb.Booster:
    """正解のある行だけで学習する。木の数は、検証の MAE が良くならなくなったところで決める。

    `below_cap_weight` は、正解が上限より下の行の重み（学習と検証の両方に付ける）。
    """
    if not math.isfinite(below_cap_weight) or below_cap_weight <= 0:
        raise ValueError("below_cap_weight must be a positive number")
    train_features, train_target_m = _rows_with_target(train_features, train_target_m)
    validation_features, validation_target_m = _rows_with_target(
        validation_features, validation_target_m
    )
    train = lgb.Dataset(
        train_features, label=train_target_m, weight=_weights(train_target_m, below_cap_weight)
    )
    validation = lgb.Dataset(
        validation_features,
        label=validation_target_m,
        weight=_weights(validation_target_m, below_cap_weight),
        reference=train,
    )
    return _train(PARAMS, train, validation)


def fit_classifier(
    train_features: pd.DataFrame,
    train_target_m: pd.Series,
    validation_features: pd.DataFrame,
    validation_target_m: pd.Series,
) -> lgb.Booster:
    """「正解が上限より下か」の分類。予測は、上限より下である確率。

    木の数は、検証の対数損失が良くならなくなったところで決める。
    """
    train_features, train_target_m = _rows_with_target(train_features, train_target_m)
    validation_features, validation_target_m = _rows_with_target(
        validation_features, validation_target_m
    )
    labels = _below_cap(train_target_m).astype("int64")
    if labels.nunique() < 2:
        raise ValueError("training rows are all on one side of the cap")
    train = lgb.Dataset(train_features, label=labels)
    validation = lgb.Dataset(
        validation_features,
        label=_below_cap(validation_target_m).astype("int64"),
        reference=train,
    )
    return _train(CLASSIFIER_PARAMS, train, validation)


def fit_below_cap(
    train_features: pd.DataFrame,
    train_target_m: pd.Series,
    validation_features: pd.DataFrame,
    validation_target_m: pd.Series,
) -> lgb.Booster:
    """正解が上限より下の行だけで、`fit` と同じ学習をする（学習・検証のどちらも）。"""
    return fit(
        train_features,
        train_target_m.where(_below_cap(train_target_m)),
        validation_features,
        validation_target_m.where(_below_cap(validation_target_m)),
    )
