"""学習の設定と学習。docs/spec.md「9. 雲底高度予測（ML）」。"""

from typing import Any

import lightgbm as lgb
import pandas as pd

from ml.features import FEATURE_NAMES

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


def fit(
    train_features: pd.DataFrame,
    train_target_m: pd.Series,
    validation_features: pd.DataFrame,
    validation_target_m: pd.Series,
) -> lgb.Booster:
    """正解のある行だけで学習する。木の数は、検証の MAE が良くならなくなったところで決める。"""
    train_features, train_target_m = _rows_with_target(train_features, train_target_m)
    validation_features, validation_target_m = _rows_with_target(
        validation_features, validation_target_m
    )
    train = lgb.Dataset(train_features, label=train_target_m)
    validation = lgb.Dataset(validation_features, label=validation_target_m, reference=train)
    return lgb.train(
        dict(PARAMS),
        train,
        num_boost_round=MAX_ROUNDS,
        valid_sets=[validation],
        valid_names=["validation"],
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )
