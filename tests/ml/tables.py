"""`ml/` のテストで使う、手で書いた小さな表。"""

import pandas as pd

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
