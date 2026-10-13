"""EDA（`notebooks/02_eda.ipynb`）で、決定の根拠になる集計。"""

import pandas as pd

from app.cities import CITIES, City
from ml.metar import CEILING_COVERS, LAYERS

# 雲の量の列（`sky_cover_1〜4`）に入りうる値。前後の空白は取ってから比べる。
KNOWN_COVERS = ("FEW", "SCT", "BKN", "OVC", "NSC", "NCD", "VV")

# `ceiling_status` が返す区分。
NO_METAR = "no_metar"
NO_LAYERS = "no_layers"
NO_CEILING_LAYER = "no_ceiling_layer"
CEILING = "ceiling"
CEILING_SKIPPED_LAYER = "ceiling_skipped_layer"
HEIGHT_UNKNOWN = "height_unknown"
VERTICAL_VISIBILITY = "vertical_visibility"
STATUSES = (
    NO_METAR,
    NO_LAYERS,
    NO_CEILING_LAYER,
    CEILING,
    CEILING_SKIPPED_LAYER,
    HEIGHT_UNKNOWN,
    VERTICAL_VISIBILITY,
)

# `skipped_layer_position` が返す値。
BELOW = "below"
ABOVE = "above"

SEASONS = ("winter", "spring", "summer", "autumn")
# 概算式 `125 × (気温 − 露点)` [m] の係数（docs/spec.md「9. ベースライン」）。
RULE_OF_THUMB_M_PER_C = 125.0


_COVER_COLUMNS = {layer: f"sky_cover_{layer}" for layer in LAYERS}
_HEIGHT_COLUMNS = {layer: f"sky_height_{layer}_m" for layer in LAYERS}


def _layers(observations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """雲の層の（量, 高さ）。列は層の番号。量は前後の空白を取り、知らない値があれば ValueError。"""
    required = ("metar", *_COVER_COLUMNS.values(), *_HEIGHT_COLUMNS.values())
    if any(name not in observations.columns for name in required):
        raise ValueError("observations do not have the expected columns")
    covers = pd.DataFrame(
        {layer: observations[name].str.strip() for layer, name in _COVER_COLUMNS.items()}
    )
    if not (covers.isna() | covers.isin(KNOWN_COVERS)).all(axis=None):
        raise ValueError("unknown sky cover")
    heights = pd.DataFrame({layer: observations[name] for layer, name in _HEIGHT_COLUMNS.items()})
    return covers, heights


def _ceiling_layers(
    covers: pd.DataFrame, heights: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """BKN・OVC の層のうち、（高さのある層, 高さのない層）。"""
    is_ceiling = covers.isin(CEILING_COVERS)
    return is_ceiling & heights.notna(), is_ceiling & heights.isna()


def ceiling_status(observations: pd.DataFrame) -> pd.Series:
    """各行（都市 × 正時）を、シーリングの決まり方で 1 つの区分に分ける。

    BKN・OVC があれば、`VV` より先に BKN・OVC の区分にする
    （`ceiling_m` が BKN・OVC から決まるため）。
    """
    covers, heights = _layers(observations)
    with_height, without_height = _ceiling_layers(covers, heights)
    has_known = with_height.any(axis=1)
    has_unknown = without_height.any(axis=1)
    # 後に書いた条件が優先される。
    steps = [
        (covers.notna().any(axis=1), NO_CEILING_LAYER),
        (covers.isin(["VV"]).any(axis=1), VERTICAL_VISIBILITY),
        (has_unknown, HEIGHT_UNKNOWN),
        (has_known, CEILING),
        (has_known & has_unknown, CEILING_SKIPPED_LAYER),
        (observations["metar"].isna(), NO_METAR),
    ]
    status = pd.Series(NO_LAYERS, index=observations.index, dtype="str", name="ceiling_status")
    for condition, value in steps:
        status = status.mask(condition, value)
    return status


def skipped_layer_position(observations: pd.DataFrame) -> pd.Series:
    """高さのない BKN・OVC の層が、`ceiling_m` を決めた層より下（前）にあるか上（後）にあるか。

    下にも上にもあれば下。飛ばした層がない行、`ceiling_m` が決まらない行は欠損。
    """
    covers, heights = _layers(observations)
    with_height, without_height = _ceiling_layers(covers, heights)
    numbers = pd.DataFrame({layer: float(layer) for layer in LAYERS}, index=observations.index)
    known = heights.where(with_height)
    decided = numbers.where(known.eq(known.min(axis=1), axis=0)).min(axis=1)
    first_unknown = numbers.where(without_height).min(axis=1)
    position = pd.Series(None, index=observations.index, dtype="str", name="skipped_layer_position")
    position = position.mask(first_unknown > decided, ABOVE)
    return position.mask(first_unknown < decided, BELOW)


def _local_time(observations: pd.DataFrame, part: str) -> pd.Series:
    """`time`（UTC）を `city` のタイムゾーンに直し、その時（hour）または月（month）を返す。"""
    time = observations["time"]
    dtype = time.dtype
    if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
        raise ValueError("time must be timezone-aware UTC")
    values = pd.Series(0, index=observations.index, dtype="int64")
    for name in observations["city"].unique():
        timezone = CITIES[City(name)].timezone
        rows = (observations["city"] == name).to_numpy()
        local = time[rows].dt.tz_convert(timezone).dt
        values.iloc[rows] = (local.hour if part == "hour" else local.month).to_numpy()
    return values


def local_hour(observations: pd.DataFrame) -> pd.Series:
    """`time`（UTC）を、`city` のタイムゾーンでの時（0〜23）にする。"""
    return _local_time(observations, "hour").rename("local_hour")


def season(observations: pd.DataFrame) -> pd.Series:
    """現地の月から季節を付ける（冬 12〜2 月、春 3〜5 月、夏 6〜8 月、秋 9〜11 月）。"""
    month = _local_time(observations, "month")
    names = {number: SEASONS[(number % 12) // 3] for number in range(1, 13)}
    return month.map(names).astype("str").rename("season")


def dew_point_spread_c(temperature_c: pd.Series, dew_point_c: pd.Series) -> pd.Series:
    """気温 − 露点（℃）。露点のほうが高ければ負のまま返す。"""
    return (temperature_c - dew_point_c).astype("float64")


def rule_of_thumb_m(spread_c: pd.Series) -> pd.Series:
    """概算式 `125 × (気温 − 露点)` [m]。"""
    return (spread_c * RULE_OF_THUMB_M_PER_C).astype("float64")
