"""目的変数（雲底高度の予測の正解）を作る。docs/spec.md「9. 目的変数」。"""

import pandas as pd

from ml.metar import CEILING_COVERS, LAYERS

# シーリングなし・上限より高いシーリングを打ち切る値（5,000 フィート）。
CEILING_CAP_M = 1524.0
# 雲の量の列（`sky_cover_1〜4`）に入りうる値。前後の空白は取ってから比べる。
KNOWN_COVERS = ("FEW", "SCT", "BKN", "OVC", "NSC", "NCD", "VV")
# 高さがあればシーリングとして数える雲の量（`VV` は鉛直視程）。
TARGET_COVERS = (*CEILING_COVERS, "VV")

_COVER_COLUMNS = {layer: f"sky_cover_{layer}" for layer in LAYERS}
_HEIGHT_COLUMNS = {layer: f"sky_height_{layer}_m" for layer in LAYERS}


def layers(observations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
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


def target_m(observations: pd.DataFrame) -> pd.Series:
    """目的変数（m）。学習・評価から除く行は欠損。

    BKN・OVC・`VV` のうち高さのある層の、最も低い高さを上限で打ち切る（高さのない層は飛ばす）。
    それらの層がなければ上限。層があるのにどれにも高さがない行、METAR のない行は欠損。
    """
    covers, heights = layers(observations)
    is_target_layer = covers.isin(TARGET_COVERS)
    lowest = heights.where(is_target_layer).min(axis=1).clip(upper=CEILING_CAP_M)
    values = lowest.mask(~is_target_layer.any(axis=1), CEILING_CAP_M)
    values = values.mask(observations["metar"].isna())
    return values.astype("float64").rename("target_m")
