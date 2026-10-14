"""雲底高度の予測（`/cloud-base`）。特徴量と予測は `ml/` のものを使う。"""

import logging
import math
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from app.cache import Cache
from app.cities import City
from app.clients.open_meteo import OpenMeteoClient
from app.errors import UpstreamError
from app.schemas import CloudBaseResponse
from app.services.forecast import INVALID_RESPONSE_ERRORS, MAX_HOURLY_ROWS, latest_hour
from app.services.weather import Clock, Source, get_forecast
from ml import model as ml_model
from ml.archive import VARIABLES
from ml.baseline import baseline_m
from ml.features import features
from ml.model import CloudBaseModel, ModelLoadError

logger = logging.getLogger(__name__)

# リポジトリで作って git に入れたファイルだけを読む（利用者の入力・環境変数からパスを作らない）。
MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "cloud_base.joblib"
# timeformat=unixtime で呼んでいるときの、時刻の単位の表記。
_TIME_UNIT = "unixtime"


class _RawRow(BaseModel):
    """Open-Meteo の hourly の 1 行のうち、特徴量に使う項目。欠けている・null・型違いは落とす。"""

    # 数値の文字列や真偽値を数値として受け付けない。NaN・無限大も落とす
    # （JSON の読み込みが NaN という書き方を受け付けるので、数値として届きうる）。
    model_config = ConfigDict(strict=True, allow_inf_nan=False)

    temperature_2m: float
    dew_point_2m: float
    relative_humidity_2m: float
    pressure_msl: float
    wind_speed_10m: float
    cloud_cover: float
    cloud_cover_low: float
    cloud_cover_mid: float
    cloud_cover_high: float
    precipitation: float


def load_model() -> CloudBaseModel | None:
    """起動のときに 1 回だけ呼ぶ。読めなければ None（`/cloud-base` だけが 503 になる）。"""
    try:
        return ml_model.load(MODEL_PATH)
    except ModelLoadError:
        # パスと例外の文面は出さない。
        logger.warning("cloud base model could not be loaded; /cloud-base will return 503")
        return None


def valid_at(now: datetime) -> datetime:
    """予測する時刻。現在以前の、最も近い正時（UTC）。"""
    return latest_hour(now)


def _check_units(raw: Mapping[str, Any]) -> None:
    """学習データを作るとき（ml/archive.py）と同じ単位でなければ、取り違えずにエラーにする。"""
    units = raw.get("hourly_units")
    if not isinstance(units, Mapping):
        raise ValueError("hourly_units is not an object")
    expected = {"time": _TIME_UNIT, **{name: VARIABLES[name][1] for name in _RawRow.model_fields}}
    for name, unit in expected.items():
        if units.get(name) != unit:
            raise ValueError("unexpected hourly unit")


def _select_rows(raw: Mapping[str, Any], ats: list[datetime]) -> list[_RawRow]:
    """hourly から、その時刻の行を順に選んで検証する。1 つでも使えなければ ValueError。"""
    _check_units(raw)
    section = raw.get("hourly")
    if not isinstance(section, Mapping):
        raise ValueError("hourly is not an object")
    times = section.get("time")
    if not isinstance(times, list) or len(times) > MAX_HOURLY_ROWS:
        raise ValueError("hourly time is missing or too long")
    if not all(type(value) is int for value in times):
        raise ValueError("hourly time is not unix seconds")
    columns: dict[str, list[Any]] = {}
    for name in _RawRow.model_fields:
        column = section.get(name)
        # 長さが違う列は、どの行がどの時刻か分からない。
        if not isinstance(column, list) or len(column) != len(times):
            raise ValueError("hourly column is missing or has an unexpected length")
        columns[name] = column
    selected: list[_RawRow] = []
    for at in ats:
        # hourly は取得時の正時の 24 時間前から入っている
        # （#15 より前の保存値は、現地の今日 0 時から）。なければ、その時刻の予測はできない。
        row = times.index(int(at.timestamp()))
        # 使う行だけを検証する（先の時刻は値が null のことがあるため）。
        selected.append(
            _RawRow.model_validate({name: column[row] for name, column in columns.items()})
        )
    return selected


def input_rows(city: City, raw: Mapping[str, Any], ats: list[datetime]) -> pd.DataFrame:
    """hourly からその時刻の行を選び、`ml.features.features` に渡す表にする（時刻の順）。

    使えない行があれば ValueError などの INVALID_RESPONSE_ERRORS（呼ぶ側で UpstreamError にする）。
    """
    rows = _select_rows(raw, ats)
    table = pd.DataFrame({"city": [city.value] * len(ats), "time": pd.to_datetime(ats, utc=True)})
    for name in _RawRow.model_fields:
        # 学習データを作るとき（ml/archive.py）と同じ対応で、列の名前を付ける。
        column, _ = VARIABLES[name]
        table[column] = pd.Series([getattr(row, name) for row in rows], dtype="float64")
    return table


def input_row(city: City, raw: Mapping[str, Any], now: datetime) -> pd.DataFrame:
    """hourly から `valid_at` の行を選び、`ml.features.features` に渡す 1 行の表にする。"""
    try:
        return input_rows(city, raw, [valid_at(now)])
    except INVALID_RESPONSE_ERRORS as exc:
        logger.warning("open-meteo response has no usable hourly row for cloud base")
        raise UpstreamError("invalid hourly row") from exc


def _round_m(value: float) -> int:
    # 四捨五入（0.5 は切り上げ）。値は 0 以上。
    return math.floor(value + 0.5)


def predict_rows(model: CloudBaseModel, table: pd.DataFrame) -> tuple[list[int], list[int]]:
    """表の各行の予測と概算式（どちらも 0〜1,524 m の整数）。モデルは 1 回だけ呼ぶ。"""
    predicted = ml_model.predict_m(model, features(table))
    baseline = baseline_m(table["temperature_c"], table["dew_point_c"])
    return (
        [_round_m(float(value)) for value in predicted],
        [_round_m(float(value)) for value in baseline],
    )


def build_cloud_base_response(
    city: City, raw: Mapping[str, Any], now: datetime, model: CloudBaseModel
) -> CloudBaseResponse:
    table = input_row(city, raw, now)
    predicted, baseline = predict_rows(model, table)
    return CloudBaseResponse(
        city=city.value,
        valid_at=valid_at(now),
        predicted_m=predicted[0],
        baseline_m=baseline[0],
        model_version=model.model_version,
    )


async def get_cloud_base(
    city: City,
    client: OpenMeteoClient,
    clock: Clock,
    cache: Cache,
    ttl_s: int,
    stale_max_age_s: int,
    model: CloudBaseModel,
) -> CloudBaseResponse:
    """`/weather` と同じ保存値・同じ決まり（TTL・stale）で予報を取り、その行で予測する。"""

    def build(raw: Mapping[str, Any], source: Source) -> CloudBaseResponse:
        return build_cloud_base_response(city, raw, source.now, model)

    return await get_forecast(city, client, clock, cache, ttl_s, stale_max_age_s, build)
