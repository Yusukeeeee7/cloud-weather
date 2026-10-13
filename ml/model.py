"""学習済みモデルの保存・読み込みと予測。ノートブックと API（#12）の両方から使う。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import pandas as pd

from ml.features import FEATURE_NAMES
from ml.target import CEILING_CAP_M

# v1 は #11 のモデル（`models/cloud_base_v1.joblib`。記録として残す）。
# v2 は #17 で選んだ 2 段階のモデル。テストの年で成功基準を満たしたので、API は v2 を出す。
MODEL_VERSION_V1 = "2026-10-13-lgbm-v1"
MODEL_VERSION_V2 = "2026-10-13-lgbm-v2"
MODEL_VERSION = MODEL_VERSION_V2
_CONTENT_KEYS = {"booster", "train_years", "feature_names", "model_version", "cap_m"}
# 2 段階のモデルのファイルにだけ入るキー。
_TWO_STAGE_KEYS = {"classifier", "below_cap_threshold"}


class ModelLoadError(Exception):
    """モデルのファイルがない・読めない・期待した形でない。"""


@dataclass(frozen=True)
class CloudBaseModel:
    """`classifier` と `below_cap_threshold` があれば 2 段階（#17）。

    2 段階では、`classifier`（上限より下である確率）が閾値以上の行だけ `booster` の値を使い、
    ほかの行は上限と答える。
    """

    booster: lgb.Booster
    train_years: tuple[int, ...]
    feature_names: tuple[str, ...] = FEATURE_NAMES
    model_version: str = MODEL_VERSION
    cap_m: float = CEILING_CAP_M
    classifier: lgb.Booster | None = None
    below_cap_threshold: float | None = None

    def __post_init__(self) -> None:
        if (self.classifier is None) != (self.below_cap_threshold is None):
            raise ValueError("classifier and below_cap_threshold must be given together")
        if self.below_cap_threshold is not None and not 0.0 < self.below_cap_threshold < 1.0:
            raise ValueError("below_cap_threshold must be between 0 and 1")


def predict_m(model: CloudBaseModel, features: pd.DataFrame) -> pd.Series:
    """予測（m）。目的変数と同じ範囲（0〜上限）に収める。列の名前・順が違えば ValueError。"""
    if list(features.columns) != list(model.feature_names):
        raise ValueError("features do not have the expected columns")
    values = pd.Series(model.booster.predict(features), index=features.index, dtype="float64")
    if model.classifier is not None and model.below_cap_threshold is not None:
        probability = pd.Series(
            model.classifier.predict(features), index=features.index, dtype="float64"
        )
        values = values.where(probability >= model.below_cap_threshold, model.cap_m)
    return values.clip(lower=0.0, upper=model.cap_m).rename("predicted_m")


def save(model: CloudBaseModel, path: Path) -> None:
    content: dict[str, Any] = {
        "booster": model.booster,
        "train_years": list(model.train_years),
        "feature_names": list(model.feature_names),
        "model_version": model.model_version,
        "cap_m": model.cap_m,
    }
    # 1 段階のモデルのファイルは、v1 と同じ中身のままにする。
    if model.classifier is not None:
        content["classifier"] = model.classifier
        content["below_cap_threshold"] = model.below_cap_threshold
    joblib.dump(content, path)


def _two_stage(content: dict[str, Any]) -> tuple[lgb.Booster | None, float | None]:
    """ファイルの中身から（分類のモデル, 閾値）。1 段階なら（None, None）。"""
    if set(content) == _CONTENT_KEYS:
        return None, None
    if set(content) != _CONTENT_KEYS | _TWO_STAGE_KEYS:
        raise ModelLoadError("model file does not have the expected content")
    classifier, threshold = content["classifier"], content["below_cap_threshold"]
    if not isinstance(classifier, lgb.Booster) or type(threshold) is not float:
        raise ModelLoadError("model file does not have the expected content")
    return classifier, threshold


def load(path: Path) -> CloudBaseModel:
    """保存したモデルを読む。読み込むとコードを実行できる形式なので、リポジトリのファイルだけに使う。"""
    try:
        content = joblib.load(path)
    except Exception as error:
        # ファイルがない・壊れている場合。壊れ方によって例外の種類が違うので、まとめて受ける。
        raise ModelLoadError("model file cannot be read") from error
    if not isinstance(content, dict):
        raise ModelLoadError("model file does not have the expected content")
    classifier, threshold = _two_stage(content)
    if not isinstance(content["booster"], lgb.Booster):
        raise ModelLoadError("model file does not have the expected content")
    if tuple(content["feature_names"]) != FEATURE_NAMES:
        raise ModelLoadError("model was made with other features")
    try:
        return CloudBaseModel(
            booster=content["booster"],
            train_years=tuple(content["train_years"]),
            feature_names=tuple(content["feature_names"]),
            model_version=content["model_version"],
            cap_m=content["cap_m"],
            classifier=classifier,
            below_cap_threshold=threshold,
        )
    except ValueError as error:
        raise ModelLoadError("model file does not have the expected content") from error
