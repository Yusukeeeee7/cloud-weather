"""`ml/` のテストで使う、手で書いた小さな表。"""

import pandas as pd

from ml import archive, dataset, metar
from tests.ml import refs

Layer = tuple[str | None, float | None]


def layer_row(layers: list[Layer], report: str | None = "XXXX 150000Z") -> dict[str, object]:
    """手で書いた 1 行。雲の層は（量, 高さ（m））を下から順に。"""
    padded = [*layers, *[(None, None)] * (4 - len(layers))]
    row: dict[str, object] = {"metar": report}
    for number, (cover, height) in enumerate(padded, start=1):
        row[f"sky_cover_{number}"] = cover
        row[f"sky_height_{number}_m"] = height
    return row


def layer_table(*rows: dict[str, object]) -> pd.DataFrame:
    table = pd.DataFrame(list(rows))
    for name in table.columns:
        dtype = "float64" if name.endswith("_m") else "str"
        table[name] = table[name].astype(dtype)
    return table


def times(city: str, *values: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "city": pd.Series([city] * len(values), dtype="str"),
            "time": pd.to_datetime(list(values), utc=True),
        }
    )


def meters(*values: float | None) -> pd.Series:
    return pd.Series(list(values), dtype="float64")


WEATHER_COLUMNS = (
    "temperature_c",
    "dew_point_c",
    "relative_humidity",
    "pressure_msl_hpa",
    "precipitation_mm",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "wind_speed_ms",
)


def weather_table(city: str, *values: str) -> pd.DataFrame:
    """`times` に Open-Meteo の列を足した表。値は行・列ごとに違う、手で決めた数。"""
    table = times(city, *values)
    for offset, name in enumerate(WEATHER_COLUMNS):
        table[name] = [float(10 * offset + row) for row in range(len(values))]
    return table


def feature_table(names: tuple[str, ...], varying: str, values: list[float]) -> pd.DataFrame:
    """列が `names` の表。`varying` の列だけ `values`、ほかの列はすべて 0。"""
    table = pd.DataFrame({name: [0.0] * len(values) for name in names})
    table[varying] = values
    return table


def step_training_table(names: tuple[str, ...], varying: str) -> tuple[pd.DataFrame, pd.Series]:
    """学習用の、手で作った（特徴量, 正解）。200 行。

    `varying` の列が 0〜9.95。5 以上の行の正解は上限（1,524 m）、5 未満の行は 300 m。
    """
    values = [row / 20 for row in range(200)]
    target = pd.Series([1524.0 if value >= 5 else 300.0 for value in values], dtype="float64")
    return feature_table(names, varying, values), target


def sample_observations() -> pd.DataFrame:
    """保存済みの実レスポンス（2 都市 × 2 日ぶん）から作った表。METAR の列も入っている。"""
    parts = {
        city: (
            archive.parse_archive(refs.archive_text(city)),
            metar.parse_metar(refs.metar_text(city)),
        )
        for city in refs.CITIES
    }
    return dataset.build_dataset(parts)
