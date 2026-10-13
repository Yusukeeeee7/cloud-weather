"""EDA（`notebooks/02_eda.ipynb`）で、決定の根拠になる集計。"""

import pandas as pd

from ml.baseline import RULE_OF_THUMB_M_PER_C as RULE_OF_THUMB_M_PER_C
from ml.baseline import rule_of_thumb_m as rule_of_thumb_m
from ml.features import SEASONS as SEASONS
from ml.features import dew_point_spread_c as dew_point_spread_c
from ml.features import local_hour as local_hour
from ml.features import season as season
from ml.metar import CEILING_COVERS, LAYERS
from ml.target import KNOWN_COVERS as KNOWN_COVERS
from ml.target import layers as _layers

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
