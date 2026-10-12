import pandas as pd
import pytest

from ml.metar import ceiling_m, parse_metar
from tests.ml.refs import (
    CITIES,
    METAR_COLUMNS,
    METERS_PER_FOOT,
    METERS_PER_MILE,
    metar_rows,
    metar_text,
    reported_ceiling_feet,
    reported_temperature_c,
)

HEADER = (
    "station,valid,tmpf,dwpf,vsby,skyc1,skyc2,skyc3,skyc4,skyl1,skyl2,skyl3,skyl4,wxcodes,metar"
)
ROW_A = "RJTT,2025-01-15 00:00,50.00,32.00,6.21,FEW,BKN,,,3000.00,4500.00,,,,RJTT 150000Z A"
ROW_B = "RJTT,2025-01-15 00:30,53.60,33.80,6.21,FEW,,,,3000.00,,,,-RA BR,RJTT 150030Z B"
FLOAT_COLUMNS = [
    "metar_temperature_c",
    "metar_dew_point_c",
    "visibility_m",
    "sky_height_1_m",
    "sky_height_2_m",
    "sky_height_3_m",
    "sky_height_4_m",
    "ceiling_m",
]
TEXT_COLUMNS = [
    "station",
    "sky_cover_1",
    "sky_cover_2",
    "sky_cover_3",
    "sky_cover_4",
    "weather_codes",
    "metar",
]


def _csv(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


def _layers(covers: list[str | None], heights: list[float | None]) -> pd.DataFrame:
    """雲の層 4 つぶんの 1 行の表（量と高さ[m]）。"""
    data: dict[str, list[object]] = {}
    for index in range(4):
        data[f"sky_cover_{index + 1}"] = [covers[index] if index < len(covers) else None]
        data[f"sky_height_{index + 1}_m"] = [heights[index] if index < len(heights) else None]
    return pd.DataFrame(data)


@pytest.mark.parametrize("city", CITIES)
def test_parse_metar_columns_and_types(city: str) -> None:
    source = metar_rows(city)

    table = parse_metar(metar_text(city))

    assert list(table.columns) == METAR_COLUMNS
    assert len(table) == len(source)
    assert str(table["observed_at"].dt.tz) == "UTC"
    for column in FLOAT_COLUMNS:
        assert pd.api.types.is_float_dtype(table[column]), column
    for column in TEXT_COLUMNS:
        assert pd.api.types.is_string_dtype(table[column]), column
    assert set(table["station"]) == {source[0]["station"]}
    # 時刻は fixture の valid（UTC で取得した「YYYY-MM-DD HH:MM」）。
    assert table["observed_at"].iloc[0] == pd.Timestamp(source[0]["valid"], tz="UTC")
    assert table["observed_at"].iloc[-1] == pd.Timestamp(source[-1]["valid"], tz="UTC")
    assert list(table["metar"]) == [row["metar"] for row in source]


@pytest.mark.parametrize("city", CITIES)
def test_parse_metar_converts_feet_and_miles_to_meters(city: str) -> None:
    source = metar_rows(city)

    table = parse_metar(metar_text(city))

    checked = 0
    for index, row in enumerate(source):
        for layer in range(1, 5):
            feet = row[f"skyl{layer}"]
            if feet:
                actual = table[f"sky_height_{layer}_m"].iloc[index]
                assert actual == pytest.approx(float(feet) * METERS_PER_FOOT)
                checked += 1
        if row["vsby"]:
            expected = float(row["vsby"]) * METERS_PER_MILE
            assert table["visibility_m"].iloc[index] == pytest.approx(expected)
    assert checked > 0


@pytest.mark.parametrize("city", CITIES)
def test_parse_metar_temperature_matches_the_report(city: str) -> None:
    # 電文の「気温/露点」は摂氏の整数。IEM の華氏の値を直すと、その整数に戻る。
    table = parse_metar(metar_text(city))

    for index, report in enumerate(table["metar"]):
        temperature, dew_point = reported_temperature_c(report)
        assert table["metar_temperature_c"].iloc[index] == pytest.approx(temperature, abs=0.01)
        assert table["metar_dew_point_c"].iloc[index] == pytest.approx(dew_point, abs=0.01)


@pytest.mark.parametrize("city", CITIES)
def test_parse_metar_missing_values(city: str) -> None:
    source = metar_rows(city)

    table = parse_metar(metar_text(city))

    empty_cells = 0
    for index, row in enumerate(source):
        for layer in range(1, 5):
            if not row[f"skyc{layer}"]:
                assert pd.isna(table[f"sky_cover_{layer}"].iloc[index])
                empty_cells += 1
            else:
                assert table[f"sky_cover_{layer}"].iloc[index] == row[f"skyc{layer}"]
            if not row[f"skyl{layer}"]:
                assert pd.isna(table[f"sky_height_{layer}_m"].iloc[index])
        if not row["wxcodes"]:
            assert pd.isna(table["weather_codes"].iloc[index])
        else:
            assert table["weather_codes"].iloc[index] == row["wxcodes"]
    assert empty_cells > 0


def test_parse_metar_keeps_layer_without_height() -> None:
    # 実レスポンスにある形：電文「FEW030 SCT///」は、量が SCT で高さが空。
    source = metar_rows("tokyo")
    index = next(i for i, row in enumerate(source) if row["skyc2"] and not row["skyl2"])
    assert "///" in source[index]["metar"]

    table = parse_metar(metar_text("tokyo"))

    assert table["sky_cover_2"].iloc[index] == source[index]["skyc2"]
    assert pd.isna(table["sky_height_2_m"].iloc[index])


@pytest.mark.parametrize(
    ("covers", "heights", "expected"),
    [
        (["FEW", "BKN", "OVC"], [300.0, 900.0, 1500.0], 900.0),
        (["OVC"], [60.0], 60.0),
        (["FEW", "SCT", "BKN", "OVC"], [300.0, 600.0, 900.0, 1200.0], 900.0),
        (["BKN", "BKN"], [150.0, 240.0], 150.0),
        # 層が高さの順に並んでいなくても、最も低いものを取る。
        (["OVC", "BKN"], [1500.0, 900.0], 900.0),
    ],
)
def test_ceiling_is_lowest_bkn_or_ovc(
    covers: list[str | None], heights: list[float | None], expected: float
) -> None:
    result = ceiling_m(_layers(covers, heights))

    assert result.iloc[0] == expected


@pytest.mark.parametrize(
    ("covers", "heights"),
    [
        ([], []),
        (["FEW"], [900.0]),
        (["FEW", "SCT"], [900.0, 1500.0]),
        (["CLR"], [None]),
        (["VV"], [60.0]),
    ],
)
def test_ceiling_is_missing_without_bkn_or_ovc(
    covers: list[str | None], heights: list[float | None]
) -> None:
    result = ceiling_m(_layers(covers, heights))

    assert pd.isna(result.iloc[0])


@pytest.mark.parametrize(
    ("covers", "heights", "expected"),
    [
        # 高さが欠損の BKN は飛ばして、次の層を見る（2026-10-12 決定）。
        (["BKN", "OVC"], [None, 1200.0], 1200.0),
        (["FEW", "BKN", "BKN"], [300.0, None, 900.0], 900.0),
        (["BKN"], [None], None),
    ],
)
def test_ceiling_ignores_layers_without_height(
    covers: list[str | None], heights: list[float | None], expected: float | None
) -> None:
    result = ceiling_m(_layers(covers, heights))

    if expected is None:
        assert pd.isna(result.iloc[0])
    else:
        assert result.iloc[0] == expected


def test_ceiling_returns_one_value_per_row() -> None:
    layers = pd.concat(
        [_layers(["FEW"], [300.0]), _layers(["OVC"], [60.0]), _layers(["BKN"], [900.0])],
        ignore_index=True,
    )

    result = ceiling_m(layers)

    assert len(result) == 3
    assert pd.isna(result.iloc[0])
    assert list(result.iloc[1:]) == [60.0, 900.0]


@pytest.mark.parametrize("city", CITIES)
def test_ceiling_matches_the_report(city: str) -> None:
    # 電文（いまの観測の部分）の BKN・OVC のうち最も低い高さと一致する。
    table = parse_metar(metar_text(city))

    with_ceiling = 0
    for index, report in enumerate(table["metar"]):
        feet = reported_ceiling_feet(report)
        actual = table["ceiling_m"].iloc[index]
        if feet is None:
            assert pd.isna(actual), report
        else:
            assert actual == pytest.approx(feet * METERS_PER_FOOT), report
            with_ceiling += 1
    assert with_ceiling > 0


def test_fixture_has_rows_with_and_without_ceiling() -> None:
    # テストの材料として、シーリングのある行・ない行の両方が fixture に入っていること。
    reports = [row["metar"] for city in CITIES for row in metar_rows(city)]
    ceilings = [reported_ceiling_feet(report) for report in reports]

    assert any(value is None for value in ceilings)
    assert any(value is not None for value in ceilings)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n",
        "<html><body>Service Unavailable</body></html>",
        HEADER + "\n",
        "station,valid,tmpf\nRJTT,2025-01-15 00:00,50.00\n",
        _csv("RJTT,2025-01-15 00:00,abc,32.00,6.21,FEW,,,,3000.00,,,,,RJTT X"),
        _csv("RJTT,15/01/2025 00:00,50.00,32.00,6.21,FEW,,,,3000.00,,,,,RJTT X"),
        _csv("RJTT,2025-01-15 00:00,50.00,32.00,6.21,FEW,,,,-100.00,,,,,RJTT X"),
    ],
)
def test_parse_metar_rejects_unexpected_format(text: str) -> None:
    with pytest.raises(ValueError):
        parse_metar(text)


def test_parse_metar_drops_exact_duplicates() -> None:
    table = parse_metar(_csv(ROW_A, ROW_A, ROW_B))

    assert len(table) == 2
    assert list(table["metar"]) == ["RJTT 150000Z A", "RJTT 150030Z B"]


def test_parse_metar_is_sorted_by_time() -> None:
    table = parse_metar(_csv(ROW_B, ROW_A))

    assert list(table["metar"]) == ["RJTT 150000Z A", "RJTT 150030Z B"]
    assert table["observed_at"].is_monotonic_increasing
    assert list(table.index) == [0, 1]


def test_parse_metar_ignores_extra_columns() -> None:
    # fixture は、アプリが要求する列より多い列（relh など）で取得してある。
    assert "relh" in metar_rows("tokyo")[0]

    table = parse_metar(metar_text("tokyo"))

    assert list(table.columns) == METAR_COLUMNS


def test_parse_metar_small_example() -> None:
    table = parse_metar(_csv(ROW_A, ROW_B))

    first = table.iloc[0]
    assert first["metar_temperature_c"] == pytest.approx(10.0)
    assert first["metar_dew_point_c"] == pytest.approx(0.0)
    assert first["sky_height_1_m"] == pytest.approx(3000 * METERS_PER_FOOT)
    assert first["ceiling_m"] == pytest.approx(4500 * METERS_PER_FOOT)
    assert pd.isna(table.iloc[1]["ceiling_m"])
    assert table.iloc[1]["weather_codes"] == "-RA BR"
