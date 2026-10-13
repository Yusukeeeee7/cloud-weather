"""学習済みモデルの保存・読み込みと予測。ノートブックと API（#12）の両方から使う。"""

from dataclasses import dataclass
from pathlib import Path

import joblib
import lightgbm as lgb
import pandas as pd

from ml.features import FEATURE_NAMES
from ml.target import CEILING_CAP_M

MODEL_VERSION = "2026-10-13-lgbm-v1"
_CONTENT_KEYS = {"booster", "train_years", "feature_names", "model_version", "cap_m"}


class ModelLoadError(Exception):
    """モデルのファイルがない・読めない・期待した形でない。"""


@dataclass(frozen=True)
class CloudBaseModel:
    booster: lgb.Booster
    train_years: tuple[int, ...]
    feature_names: tuple[str, ...] = FEATURE_NAMES
    model_version: str = MODEL_VERSION
    cap_m: float = CEILING_CAP_M


def predict_m(model: CloudBaseModel, features: pd.DataFrame) -> pd.Series:
    """予測（m）。目的変数と同じ範囲（0〜上限）に収める。列の名前・順が違えば ValueError。"""
    if list(features.columns) != list(model.feature_names):
        raise ValueError("features do not have the expected columns")
    values = pd.Series(model.booster.predict(features), index=features.index, dtype="float64")
    return values.clip(lower=0.0, upper=model.cap_m).rename("predicted_m")


def save(model: CloudBaseModel, path: Path) -> None:
    content = {
        "booster": model.booster,
        "train_years": list(model.train_years),
        "feature_names": list(model.feature_names),
        "model_version": model.model_version,
        "cap_m": model.cap_m,
    }
    joblib.dump(content, path)


def load(path: Path) -> CloudBaseModel:
    """保存したモデルを読む。読み込むとコードを実行できる形式なので、リポジトリのファイルだけに使う。"""
    try:
        content = joblib.load(path)
    except Exception as error:
        # ファイルがない・壊れている場合。壊れ方によって例外の種類が違うので、まとめて受ける。
        raise ModelLoadError("model file cannot be read") from error
    if not isinstance(content, dict) or set(content) != _CONTENT_KEYS:
        raise ModelLoadError("model file does not have the expected content")
    if not isinstance(content["booster"], lgb.Booster):
        raise ModelLoadError("model file does not have the expected content")
    if tuple(content["feature_names"]) != FEATURE_NAMES:
        raise ModelLoadError("model was made with other features")
    return CloudBaseModel(
        booster=content["booster"],
        train_years=tuple(content["train_years"]),
        feature_names=tuple(content["feature_names"]),
        model_version=content["model_version"],
        cap_m=content["cap_m"],
    )
