"""IEM の METAR の過去データ（CSV）を表にする。"""

import io

import pandas as pd

from ml.archive import TIME_UNIT

# 1 フィート = 0.3048 m、1 マイル = 1609.344 m（定義値）。
METERS_PER_FOOT = 0.3048
METERS_PER_MILE = 1609.344
LAYERS = (1, 2, 3, 4)
# シーリングとして数える雲の量（docs/spec.md「9. 目的変数」）。
CEILING_COVERS = ("BKN", "OVC")
# IEM の時刻の形（tz=UTC で取得する）。
_TIME_FORMAT = "%Y-%m-%d %H:%M"
_NUMERIC = ("tmpf", "dwpf", "vsby", *(f"skyl{layer}" for layer in LAYERS))
_TEXT = ("station", *(f"skyc{layer}" for layer in LAYERS), "wxcodes", "metar")
_REQUIRED = ("valid", *_NUMERIC, *_TEXT)

COLUMNS = [
    "station",
    "observed_at",
    "metar_temperature_c",
    "metar_dew_point_c",
    "visibility_m",
    *(f"sky_cover_{layer}" for layer in LAYERS),
    *(f"sky_height_{layer}_m" for layer in LAYERS),
    "weather_codes",
    "metar",
    "ceiling_m",
]


def _read(text: str) -> pd.DataFrame:
    if not text.strip():
        raise ValueError("METAR data is empty")
    # 型の推測に任せず、文字列のまま読む（空の列が数値になるのを避ける）。
    raw = pd.read_csv(io.StringIO(text), dtype="str", keep_default_na=False)
    missing = [name for name in _REQUIRED if name not in raw.columns]
    if missing:
        raise ValueError("METAR data does not have the expected columns")
    if raw.empty:
        raise ValueError("METAR data has no rows")
    return raw


def _number(column: pd.Series) -> pd.Series:
    # 空文字は欠損。数値でない文字列は ValueError。
    return pd.to_numeric(column.mask(column == "", None), errors="raise").astype("float64")


def _text(column: pd.Series) -> pd.Series:
    return column.mask(column == "", None).astype("str")


def _fahrenheit_to_celsius(column: pd.Series) -> pd.Series:
    return (column - 32.0) * 5.0 / 9.0


def ceiling_m(layers: pd.DataFrame) -> pd.Series:
    """最も低い BKN または OVC の層の高さ（m）。なければ欠損。

    量が BKN・OVC でも高さが欠損の層は飛ばす。
    """
    heights = {
        layer: pd.to_numeric(layers[f"sky_height_{layer}_m"], errors="coerce").where(
            layers[f"sky_cover_{layer}"].isin(CEILING_COVERS)
        )
        for layer in LAYERS
    }
    return pd.DataFrame(heights).min(axis=1).astype("float64").rename("ceiling_m")


def parse_metar(text: str) -> pd.DataFrame:
    """時刻は UTC、気温は摂氏、視程・雲高はメートル。`ceiling_m` を付ける。"""
    raw = _read(text)
    table = pd.DataFrame(
        {
            "station": _text(raw["station"]),
            "observed_at": pd.to_datetime(raw["valid"], format=_TIME_FORMAT, utc=True).dt.as_unit(
                TIME_UNIT
            ),
            "metar_temperature_c": _fahrenheit_to_celsius(_number(raw["tmpf"])),
            "metar_dew_point_c": _fahrenheit_to_celsius(_number(raw["dwpf"])),
            "visibility_m": _number(raw["vsby"]) * METERS_PER_MILE,
        }
    )
    for layer in LAYERS:
        table[f"sky_cover_{layer}"] = _text(raw[f"skyc{layer}"])
    for layer in LAYERS:
        table[f"sky_height_{layer}_m"] = _number(raw[f"skyl{layer}"]) * METERS_PER_FOOT
    table["weather_codes"] = _text(raw["wxcodes"])
    table["metar"] = _text(raw["metar"])
    heights = table[[f"sky_height_{layer}_m" for layer in LAYERS]]
    if (heights < 0).any().any() or (table["visibility_m"] < 0).any():
        raise ValueError("METAR data has a negative height or visibility")
    table["ceiling_m"] = ceiling_m(table)
    table = table.drop_duplicates().sort_values("observed_at", kind="stable")
    return table.reset_index(drop=True)[COLUMNS]
