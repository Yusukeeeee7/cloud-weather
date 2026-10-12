"""`ml/` のテストで使う、保存済みの実レスポンス（tests/fixtures/data_raw/）の読み出し。

生データと同じ並び（<提供元>/<city>_<年>.<拡張子>）で置いてある。中身は 2025-01-15〜16 の 2 日ぶん。
"""

import csv
import io
import json
import re
from typing import Any

from tests.conftest import FIXTURES_DIR

RAW_ROOT = FIXTURES_DIR / "data_raw"
CITIES = ("tokyo", "berlin")
YEAR = 2025

# 1 フィート = 0.3048 m、1 マイル = 1609.344 m（どちらも定義値）。
METERS_PER_FOOT = 0.3048
METERS_PER_MILE = 1609.344

METAR_COLUMNS = [
    "station",
    "observed_at",
    "metar_temperature_c",
    "metar_dew_point_c",
    "visibility_m",
    "sky_cover_1",
    "sky_cover_2",
    "sky_cover_3",
    "sky_cover_4",
    "sky_height_1_m",
    "sky_height_2_m",
    "sky_height_3_m",
    "sky_height_4_m",
    "weather_codes",
    "metar",
    "ceiling_m",
]
ARCHIVE_COLUMNS = [
    "time",
    "temperature_c",
    "dew_point_c",
    "relative_humidity",
    "pressure_msl_hpa",
    "precipitation_mm",
    "weather_code",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "wind_speed_ms",
]
# Open-Meteo の項目名 → 表の列名。
ARCHIVE_VARIABLES = {
    "temperature_2m": "temperature_c",
    "dew_point_2m": "dew_point_c",
    "relative_humidity_2m": "relative_humidity",
    "pressure_msl": "pressure_msl_hpa",
    "precipitation": "precipitation_mm",
    "weather_code": "weather_code",
    "cloud_cover": "cloud_cover",
    "cloud_cover_low": "cloud_cover_low",
    "cloud_cover_mid": "cloud_cover_mid",
    "cloud_cover_high": "cloud_cover_high",
    "wind_speed_10m": "wind_speed_ms",
}
DATASET_COLUMNS = [
    "city",
    *ARCHIVE_COLUMNS,
    "metar_observed_at",
    *[column for column in METAR_COLUMNS if column not in ("station", "observed_at")],
]

_TEMPERATURE_GROUP = re.compile(r" (M?\d{2})/(M?\d{2}) ")
_TREND = re.compile(r" (TEMPO|BECMG|NOSIG|RMK)\b")
_CEILING_LAYER = re.compile(r"\b(?:BKN|OVC)(\d{3})\b")


def metar_text(city: str) -> str:
    # 改行を変えずに読む（raw_store と同じ読み方）。
    return (RAW_ROOT / "iem" / f"{city}_{YEAR}.csv").read_bytes().decode("utf-8")


def metar_rows(city: str) -> list[dict[str, str]]:
    """fixture の行を、列名 → 文字列のまま返す（実装を通さずに読む）。"""
    return list(csv.DictReader(io.StringIO(metar_text(city))))


def archive_text(city: str) -> str:
    return (RAW_ROOT / "open_meteo_archive" / f"{city}_{YEAR}.json").read_bytes().decode("utf-8")


def archive_raw(city: str) -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(archive_text(city))
    return raw


def _signed(text: str) -> int:
    return -int(text[1:]) if text.startswith("M") else int(text)


def metar_body(report: str) -> str:
    """電文のうち、いまの観測の部分（変化の予報 TEMPO・BECMG と備考 RMK より前）。"""
    trend = _TREND.search(report)
    return report if trend is None else report[: trend.start()]


def reported_temperature_c(report: str) -> tuple[int, int]:
    """電文の「気温/露点」（摂氏の整数。M はマイナス）。"""
    group = _TEMPERATURE_GROUP.search(report + " ")
    assert group is not None, report
    return _signed(group.group(1)), _signed(group.group(2))


def reported_ceiling_feet(report: str) -> int | None:
    """電文の BKN・OVC の層のうち、最も低い高さ（フィート）。なければ None。"""
    heights = [int(value) * 100 for value in _CEILING_LAYER.findall(metar_body(report))]
    return min(heights) if heights else None
