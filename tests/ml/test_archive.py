import json
from collections.abc import Callable
from typing import Any

import pandas as pd
import pytest

from ml.archive import parse_archive
from tests.ml.refs import ARCHIVE_COLUMNS, ARCHIVE_VARIABLES, CITIES, archive_raw, archive_text

Change = Callable[[dict[str, Any]], None]


def _changed(change: Change) -> str:
    raw = archive_raw("berlin")
    change(raw)
    return json.dumps(raw)


@pytest.mark.parametrize("city", CITIES)
def test_parse_archive_columns_and_types(city: str) -> None:
    hourly = archive_raw(city)["hourly"]

    table = parse_archive(archive_text(city))

    assert list(table.columns) == ARCHIVE_COLUMNS
    assert len(table) == len(hourly["time"]) == 48
    assert str(table["time"].dt.tz) == "UTC"
    assert [int(value.timestamp()) for value in table["time"]] == hourly["time"]
    for column in ARCHIVE_COLUMNS[1:]:
        assert pd.api.types.is_float_dtype(table[column]), column


@pytest.mark.parametrize("city", CITIES)
def test_parse_archive_values_match_the_response(city: str) -> None:
    hourly = archive_raw(city)["hourly"]

    table = parse_archive(archive_text(city))

    for variable, column in ARCHIVE_VARIABLES.items():
        assert list(table[column]) == [float(value) for value in hourly[variable]], variable


@pytest.mark.parametrize(
    ("variable", "unit"),
    [
        ("temperature_2m", "°F"),
        ("dew_point_2m", "°F"),
        ("wind_speed_10m", "km/h"),
        ("pressure_msl", "Pa"),
        ("precipitation", "inch"),
        ("time", "iso8601"),
    ],
)
def test_parse_archive_rejects_unexpected_units(variable: str, unit: str) -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["hourly_units"][variable] = unit

    with pytest.raises(ValueError):
        parse_archive(_changed(change))


def test_parse_archive_missing_values() -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["hourly"]["temperature_2m"][3] = None
        raw["hourly"]["weather_code"][5] = None

    table = parse_archive(_changed(change))

    assert pd.isna(table["temperature_c"].iloc[3])
    assert pd.isna(table["weather_code"].iloc[5])
    assert table["temperature_c"].notna().sum() == 47


def _drop_variable(raw: dict[str, Any]) -> None:
    del raw["hourly"]["pressure_msl"]


def _drop_units(raw: dict[str, Any]) -> None:
    del raw["hourly_units"]


def _shorten_column(raw: dict[str, Any]) -> None:
    raw["hourly"]["cloud_cover"].pop()


def _empty(raw: dict[str, Any]) -> None:
    for column in raw["hourly"].values():
        column.clear()


def _text_value(raw: dict[str, Any]) -> None:
    raw["hourly"]["temperature_2m"][0] = "2.2"


def _gap(raw: dict[str, Any]) -> None:
    for column in raw["hourly"].values():
        del column[10]


def _duplicate_time(raw: dict[str, Any]) -> None:
    raw["hourly"]["time"][1] = raw["hourly"]["time"][0]


@pytest.mark.parametrize(
    "change",
    [_drop_variable, _drop_units, _shorten_column, _empty, _text_value, _gap, _duplicate_time],
)
def test_parse_archive_rejects_unexpected_format(change: Change) -> None:
    with pytest.raises(ValueError):
        parse_archive(_changed(change))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        "{}",
        '{"error": true, "reason": "Parameter start_date is out of allowed range"}',
        '{"hourly": []}',
    ],
)
def test_parse_archive_rejects_non_forecast_bodies(text: str) -> None:
    with pytest.raises(ValueError):
        parse_archive(text)
