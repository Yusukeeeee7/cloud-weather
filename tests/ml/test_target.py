import math

import pandas as pd
import pytest

from ml import eda, target
from ml.metar import parse_metar
from tests.ml.refs import CITIES, METERS_PER_FOOT, metar_text, reported_cloud_groups
from tests.ml.tables import Layer, layer_row, layer_table

# docs/spec.md「9. 目的変数」：上限は 1,524 m（5,000 フィート）。
CAP_M = 1524.0


def _target(layers: list[Layer], report: str | None = "XXXX 150000Z") -> float:
    values = target.target_m(layer_table(layer_row(layers, report)))
    assert len(values) == 1
    return float(values.iloc[0])


def test_cap_is_5000_feet() -> None:
    assert target.CEILING_CAP_M == CAP_M
    assert pytest.approx(5000 * METERS_PER_FOOT) == target.CEILING_CAP_M


@pytest.mark.parametrize(
    ("layers", "expected"),
    [
        ([("BKN", 300.0)], 300.0),
        ([("OVC", 60.0)], 60.0),
        ([("FEW", 150.0), ("BKN", 900.0)], 900.0),
        ([("FEW", 150.0), ("SCT", 300.0), ("BKN", 900.0), ("OVC", 1200.0)], 900.0),
        # 高さのない層が FEW・SCT なら、シーリングには関係しない。
        ([("SCT", None), ("BKN", 900.0)], 900.0),
    ],
)
def test_target_is_lowest_bkn_or_ovc_height(layers: list[Layer], expected: float) -> None:
    assert _target(layers) == expected


@pytest.mark.parametrize(
    ("layers", "expected"),
    [
        ([("BKN", 3000.0)], CAP_M),
        ([("FEW", 900.0), ("OVC", 7010.4)], CAP_M),
        # ちょうど 5,000 フィート。
        ([("BKN", 1524.0)], CAP_M),
        # 上限のすぐ下（4,900 フィート）は、そのまま。
        ([("BKN", 1493.52)], 1493.52),
    ],
)
def test_target_is_capped_at_1524(layers: list[Layer], expected: float) -> None:
    assert _target(layers) == expected


@pytest.mark.parametrize(
    "layers",
    [
        [("FEW", 900.0)],
        [("FEW", 900.0), ("SCT", 1200.0)],
        [("FEW", 900.0), ("SCT", None)],
        [("NSC", None)],
        [("NCD", None)],
    ],
)
def test_target_is_cap_without_ceiling_layer(layers: list[Layer]) -> None:
    assert _target(layers) == CAP_M


def test_target_is_cap_without_layers() -> None:
    assert _target([], report="EDDB 010020Z 21016KT CAVOK 11/06 Q0998") == CAP_M


@pytest.mark.parametrize(
    ("layers", "expected"),
    [
        # BKN030 BKN/// の形（高さのない層のほうが上）。
        ([("FEW", 300.0), ("BKN", 900.0), ("BKN", None)], 900.0),
        # FEW010 BKN/// OVC040 の形（高さのない層のほうが下）。
        ([("FEW", 300.0), ("BKN", None), ("OVC", 1200.0)], 1200.0),
        ([("BKN", 4200.0), ("BKN", None)], CAP_M),
    ],
)
def test_target_skips_layer_without_height(layers: list[Layer], expected: float) -> None:
    assert _target(layers) == expected


@pytest.mark.parametrize(
    "layers",
    [
        [("BKN", None)],
        [("FEW", 900.0), ("BKN", None)],
        [("BKN", None), ("OVC", None)],
    ],
)
def test_target_is_missing_when_no_ceiling_height(layers: list[Layer]) -> None:
    assert math.isnan(_target(layers))


@pytest.mark.parametrize(
    ("layers", "expected"),
    [
        # 保存済みのデータには、末尾に空白の付いた `VV ` で入っている。
        ([("VV ", 60.96)], 60.96),
        ([("VV", 91.44)], 91.44),
        ([("VV ", 3000.0)], CAP_M),
        # 高さのある層のうち、最も低いもの（BKN・OVC・VV を同じに扱う）。
        ([("VV ", 60.0), ("BKN", 300.0)], 60.0),
        ([("VV ", None), ("BKN", 300.0)], 300.0),
    ],
)
def test_target_counts_vertical_visibility_with_height(
    layers: list[Layer], expected: float
) -> None:
    assert _target(layers) == expected


@pytest.mark.parametrize(
    "layers", [[("VV ", None)], [("VV", None)], [("VV ", None), ("BKN", None)]]
)
def test_target_is_missing_for_vertical_visibility_without_height(layers: list[Layer]) -> None:
    assert math.isnan(_target(layers))


@pytest.mark.parametrize("layers", [[], [("BKN", 300.0)], [("FEW", 900.0)]])
def test_target_is_missing_without_metar(layers: list[Layer]) -> None:
    # METAR が付かなかった正時は、正解がない（上限の値にしない）。
    assert math.isnan(_target(layers, report=None))


@pytest.mark.parametrize("cover", [" BKN ", "OVC "])
def test_target_ignores_spaces_around_cover(cover: str) -> None:
    assert _target([(cover, 300.0)]) == 300.0


@pytest.mark.parametrize("cover", ["XXX", "bkn", "///"])
def test_target_rejects_unknown_cover(cover: str) -> None:
    with pytest.raises(ValueError, match="unknown sky cover"):
        _target([("FEW", 900.0), (cover, 1500.0)])


def test_target_rejects_missing_columns() -> None:
    table = layer_table(layer_row([("BKN", 300.0)])).drop(columns=["sky_height_4_m"])

    with pytest.raises(ValueError, match="expected columns"):
        target.target_m(table)


def _reported_target_m(report: str) -> float:
    """電文から読んだ目的変数（IEM の列も実装も通さない）。"""
    heights = [
        height for cover, height in reported_cloud_groups(report) if cover in ("BKN", "OVC", "VV")
    ]
    known = [height for height in heights if height is not None]
    if known:
        return min(min(known) * METERS_PER_FOOT, CAP_M)
    return math.nan if heights else CAP_M


def test_target_matches_fixture_reports() -> None:
    kinds: set[str] = set()
    for city in CITIES:
        table = parse_metar(metar_text(city))

        values = target.target_m(table)

        expected = [_reported_target_m(report) for report in table["metar"]]
        assert values.tolist() == pytest.approx(expected, nan_ok=True)
        for value in expected:
            kinds.add("missing" if math.isnan(value) else "cap" if value == CAP_M else "below")
    # fixture に 3 つの場合がすべて入っている（何も確かめないテストにしない）。
    assert kinds == {"missing", "cap", "below"}


def test_target_is_consistent_with_ceiling_status() -> None:
    hand_written = layer_table(
        layer_row([], report=None),
        layer_row([("VV ", None)]),
        layer_row([("VV ", 60.0)]),
        layer_row([("NSC", None)]),
    )
    tables = [*(parse_metar(metar_text(city)) for city in CITIES), hand_written]
    seen: set[str] = set()
    for table in tables:
        statuses = eda.ceiling_status(table)

        missing = target.target_m(table).isna()

        vertical_visibility_without_height = (statuses == eda.VERTICAL_VISIBILITY) & table[
            [f"sky_height_{layer}_m" for layer in (1, 2, 3, 4)]
        ].isna().all(axis=1)
        expected = (
            statuses.isin([eda.NO_METAR, eda.HEIGHT_UNKNOWN]) | vertical_visibility_without_height
        )
        assert missing.tolist() == expected.tolist()
        seen.update(statuses)
    assert seen >= {eda.NO_METAR, eda.HEIGHT_UNKNOWN, eda.VERTICAL_VISIBILITY, eda.CEILING}


def test_target_keeps_index_and_does_not_modify_input() -> None:
    table = layer_table(
        layer_row([("BKN", 300.0)]),
        layer_row([("VV ", None)]),
        layer_row([("FEW", 900.0)]),
    )
    table.index = pd.Index([30, 20, 10])
    before = table.copy(deep=True)

    values = target.target_m(table)

    assert list(values.index) == [30, 20, 10]
    assert values.name == "target_m"
    assert str(values.dtype) == "float64"
    pd.testing.assert_frame_equal(table, before)
