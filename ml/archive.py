"""Open-Meteo の過去データの応答（JSON）を表にする。"""

import json
from typing import Any, Final

import pandas as pd

# Open-Meteo の項目名 → (表の列名, 想定する単位)。単位が違えば、取り違えずにエラーにする。
VARIABLES: dict[str, tuple[str, str]] = {
    "temperature_2m": ("temperature_c", "°C"),
    "dew_point_2m": ("dew_point_c", "°C"),
    "relative_humidity_2m": ("relative_humidity", "%"),
    "pressure_msl": ("pressure_msl_hpa", "hPa"),
    "precipitation": ("precipitation_mm", "mm"),
    "weather_code": ("weather_code", "wmo code"),
    "cloud_cover": ("cloud_cover", "%"),
    "cloud_cover_low": ("cloud_cover_low", "%"),
    "cloud_cover_mid": ("cloud_cover_mid", "%"),
    "cloud_cover_high": ("cloud_cover_high", "%"),
    "wind_speed_10m": ("wind_speed_ms", "m/s"),
}
COLUMNS = ["time", *(column for column, _ in VARIABLES.values())]
_TIME_UNIT = "unixtime"
# 時刻の列の細かさ。parquet に保存して読み直しても変わらない単位（秒は ms になって戻る）。
TIME_UNIT: Final = "ms"
_HOUR_S = 3600


def _section(raw: Any, name: str) -> dict[str, Any]:
    section = raw.get(name) if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        raise ValueError(f"archive response does not have {name}")
    return section


def _check_units(units: dict[str, Any]) -> None:
    expected = {"time": _TIME_UNIT, **{name: unit for name, (_, unit) in VARIABLES.items()}}
    for name, unit in expected.items():
        if units.get(name) != unit:
            raise ValueError(f"unexpected unit for {name}")


def _times(hourly: dict[str, Any]) -> list[int]:
    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        raise ValueError("archive response has no hourly times")
    if not all(type(value) is int for value in times):
        raise ValueError("hourly time is not unix seconds")
    steps = {later - earlier for earlier, later in zip(times, times[1:], strict=False)}
    if steps - {_HOUR_S}:
        raise ValueError("hourly times are not consecutive hours")
    return times


def _values(hourly: dict[str, Any], name: str, rows: int) -> list[float | None]:
    values = hourly.get(name)
    if not isinstance(values, list) or len(values) != rows:
        raise ValueError(f"unexpected hourly column: {name}")
    for value in values:
        # null は欠損。数値の文字列や真偽値は受け付けない。
        if value is not None and type(value) not in (int, float):
            raise ValueError(f"hourly value is not a number: {name}")
    return [None if value is None else float(value) for value in values]


def parse_archive(text: str) -> pd.DataFrame:
    """1 行 = 正時（UTC）。列名に単位を付ける。"""
    raw = json.loads(text)
    hourly = _section(raw, "hourly")
    _check_units(_section(raw, "hourly_units"))
    times = _times(hourly)
    table = pd.DataFrame({"time": pd.to_datetime(times, unit="s", utc=True).as_unit(TIME_UNIT)})
    for name, (column, _) in VARIABLES.items():
        table[column] = pd.Series(_values(hourly, name, len(times)), dtype="float64")
    return table[COLUMNS]
