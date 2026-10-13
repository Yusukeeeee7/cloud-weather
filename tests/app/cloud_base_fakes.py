"""`/cloud-base` のテストで使う、モデルの代わりと、fixture から期待値を読む関数。"""

import json
from datetime import datetime
from typing import Any

import pandas as pd

from app.cities import City
from ml import archive, model
from ml.features import features
from tests.conftest import RawForecast

# docs/spec.md「9. 目的変数」：上限は 1,524 m。
CAP_M = 1524
# docs/spec.md「9. ベースライン」：概算式 `125 × (気温 − 露点)` [m]。
RULE_OF_THUMB_M_PER_C = 125.0
# 特徴量に使う Open-Meteo の項目（docs/spec.md「9. 特徴量」の「Open-Meteo の値そのまま」）。
ITEMS = (
    "temperature_2m",
    "dew_point_2m",
    "relative_humidity_2m",
    "pressure_msl",
    "wind_speed_10m",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "precipitation",
)


class RecordingBooster:
    """渡された表を記録して、決まった値を返す、モデルの代わり。"""

    def __init__(self, value: float) -> None:
        self.value = value
        self.seen: list[pd.DataFrame] = []

    def predict(self, data: pd.DataFrame, **_: Any) -> Any:
        self.seen.append(data.copy())
        return pd.Series([self.value] * len(data), dtype="float64").to_numpy()


def fake_model(
    value: float, model_version: str = "fake-v0"
) -> tuple[model.CloudBaseModel, RecordingBooster]:
    booster = RecordingBooster(value)
    fake = model.CloudBaseModel(
        booster=booster,  # type: ignore[arg-type]
        train_years=(2018,),
        model_version=model_version,
    )
    return fake, booster


def row_of(raw: RawForecast, at: datetime) -> int:
    """fixture の hourly で、その時刻の行の番号。"""
    times: list[int] = raw["hourly"]["time"]
    return times.index(int(at.timestamp()))


def half_up(value: float) -> int:
    """四捨五入（0.5 は切り上げ）。値は 0 以上のときだけ使う。"""
    return int(value + 0.5)


def expected_baseline_m(raw: RawForecast, at: datetime) -> int:
    """fixture の気温・露点から、spec の式で出した値（0〜1,524 に収めて四捨五入）。"""
    row = row_of(raw, at)
    spread = raw["hourly"]["temperature_2m"][row] - raw["hourly"]["dew_point_2m"][row]
    return half_up(min(max(RULE_OF_THUMB_M_PER_C * spread, 0.0), float(CAP_M)))


def training_features(city: City, raw: RawForecast, at: datetime) -> pd.DataFrame:
    """学習と同じ道すじ（応答 → 表 → 特徴量）で作った、その時刻の特徴量（1 行）。

    予報の hourly は、過去データと同じ項目名・単位なので、`ml.archive` でそのまま表にできる。
    """
    table = archive.parse_archive(json.dumps(raw))
    table.insert(0, "city", city.value)
    rows = table.index[table["time"] == at]
    assert len(rows) == 1
    return features(table).loc[rows].reset_index(drop=True)
