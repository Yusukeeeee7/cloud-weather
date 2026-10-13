import pandas as pd
import pytest

from ml import baseline, eda, features
from ml.metar import parse_metar
from tests.ml.refs import CITIES, metar_body, metar_text, reported_cloud_groups

Layer = tuple[str, float | None]


def _row(layers: list[Layer], report: str | None = "XXXX 150000Z") -> dict[str, object]:
    """手で書いた 1 行。雲の層は（量, 高さ（m））を下から順に。"""
    padded = [*layers, *[(None, None)] * (4 - len(layers))]
    row: dict[str, object] = {"metar": report}
    for number, (cover, height) in enumerate(padded, start=1):
        row[f"sky_cover_{number}"] = cover
        row[f"sky_height_{number}_m"] = height
    return row


def _table(*rows: dict[str, object]) -> pd.DataFrame:
    table = pd.DataFrame(list(rows))
    for name in table.columns:
        dtype = "float64" if name.endswith("_m") else "str"
        table[name] = table[name].astype(dtype)
    return table


def _status(layers: list[Layer], report: str | None = "XXXX 150000Z") -> str:
    statuses = eda.ceiling_status(_table(_row(layers, report)))
    assert len(statuses) == 1
    return str(statuses.iloc[0])


def _times(city: str, *times: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "city": pd.Series([city] * len(times), dtype="str"),
            "time": pd.to_datetime(list(times), utc=True),
        }
    )


def test_ceiling_status_no_metar() -> None:
    assert _status([], report=None) == "no_metar"


def test_ceiling_status_no_layers() -> None:
    assert _status([], report="EDDB 010020Z 21016KT CAVOK 11/06 Q0998") == "no_layers"


@pytest.mark.parametrize(
    "layers",
    [
        [("FEW", 900.0)],
        [("FEW", 900.0), ("SCT", 1500.0)],
        [("FEW", 900.0), ("SCT", None)],
        [("NSC", None)],
        [("NCD", None)],
    ],
)
def test_ceiling_status_without_bkn_or_ovc(layers: list[Layer]) -> None:
    assert _status(layers) == "no_ceiling_layer"


@pytest.mark.parametrize(
    "layers",
    [
        [("BKN", 300.0)],
        [("OVC", 300.0)],
        [("FEW", 900.0), ("BKN", 1500.0)],
        [("FEW", 900.0), ("SCT", 1200.0), ("BKN", 1500.0), ("OVC", 3000.0)],
        # 高さのない層が FEW・SCT なら、シーリングには関係しない。
        [("SCT", None), ("BKN", 1500.0)],
    ],
)
def test_ceiling_status_with_height(layers: list[Layer]) -> None:
    assert _status(layers) == "ceiling"


@pytest.mark.parametrize(
    "layers",
    [
        # FEW050 BKN/// OVC100 の形（高さのない層のほうが下）。
        [("FEW", 1500.0), ("BKN", None), ("OVC", 3000.0)],
        # BKN140 BKN/// の形（高さのない層のほうが上）。
        [("FEW", 900.0), ("BKN", 4200.0), ("BKN", None)],
    ],
)
def test_ceiling_status_skipped_layer(layers: list[Layer]) -> None:
    assert _status(layers) == "ceiling_skipped_layer"


@pytest.mark.parametrize(
    "layers",
    [
        [("BKN", None)],
        [("FEW", 900.0), ("BKN", None)],
        [("BKN", None), ("OVC", None)],
    ],
)
def test_ceiling_status_height_unknown(layers: list[Layer]) -> None:
    assert _status(layers) == "height_unknown"


@pytest.mark.parametrize(
    "layers",
    [
        # 保存済みのデータには、末尾に空白の付いた `VV ` で入っている。
        [("VV ", None)],
        [("VV", None)],
        [("VV ", 60.0)],
    ],
)
def test_ceiling_status_vertical_visibility(layers: list[Layer]) -> None:
    assert _status(layers) == "vertical_visibility"


def test_ceiling_status_bkn_or_ovc_wins_over_vertical_visibility() -> None:
    # `ceiling_m` は BKN・OVC から決まる（spec 9）ので、同時にあれば BKN・OVC の区分にする。
    assert _status([("VV ", None), ("BKN", 300.0)]) == "ceiling"


@pytest.mark.parametrize("cover", [" BKN ", "OVC "])
def test_ceiling_status_ignores_spaces_around_cover(cover: str) -> None:
    assert _status([(cover, 300.0)]) == "ceiling"


@pytest.mark.parametrize("cover", ["XXX", "bkn", "///"])
def test_ceiling_status_rejects_unknown_cover(cover: str) -> None:
    with pytest.raises(ValueError, match="unknown sky cover"):
        _status([("FEW", 900.0), (cover, 1500.0)])


def test_ceiling_status_rejects_missing_columns() -> None:
    table = _table(_row([("BKN", 300.0)])).drop(columns=["sky_height_4_m"])

    with pytest.raises(ValueError, match="expected columns"):
        eda.ceiling_status(table)


def test_ceiling_status_keeps_index_and_uses_known_values() -> None:
    table = _table(
        _row([], report=None),
        _row([]),
        _row([("FEW", 900.0)]),
        _row([("BKN", 300.0)]),
        _row([("BKN", 300.0), ("BKN", None)]),
        _row([("BKN", None)]),
        _row([("VV ", None)]),
    )
    table.index = pd.Index([70, 60, 50, 40, 30, 20, 10])

    statuses = eda.ceiling_status(table)

    assert list(statuses.index) == [70, 60, 50, 40, 30, 20, 10]
    assert statuses.name == "ceiling_status"
    assert list(statuses) == list(eda.STATUSES)


def _reported_status(report: str) -> str:
    """電文から読んだ区分（IEM の列も実装も通さない）。"""
    groups = reported_cloud_groups(report)
    ceiling_heights = [height for cover, height in groups if cover in ("BKN", "OVC")]
    if ceiling_heights:
        if all(height is None for height in ceiling_heights):
            return "height_unknown"
        if any(height is None for height in ceiling_heights):
            return "ceiling_skipped_layer"
        return "ceiling"
    if any(cover == "VV" for cover, _ in groups):
        return "vertical_visibility"
    words = metar_body(report).split()
    if groups or "NSC" in words or "NCD" in words:
        return "no_ceiling_layer"
    return "no_layers"


def test_ceiling_status_matches_fixture_rows() -> None:
    seen: set[str] = set()
    for city in CITIES:
        table = parse_metar(metar_text(city))

        statuses = eda.ceiling_status(table)

        expected = [_reported_status(report) for report in table["metar"]]
        assert list(statuses) == expected
        seen.update(expected)
    # fixture に、少なくともこの 5 つの区分が入っている（何も確かめないテストにしない）。
    assert seen >= {
        "no_layers",
        "no_ceiling_layer",
        "ceiling",
        "ceiling_skipped_layer",
        "height_unknown",
    }


@pytest.mark.parametrize(
    ("layers", "expected"),
    [
        # 高さのない層が、高さの決まった BKN・OVC より下（前）：実際のシーリングはもっと低い可能性。
        ([("FEW", 1500.0), ("BKN", None), ("OVC", 3000.0)], "below"),
        ([("BKN", None), ("BKN", 3000.0)], "below"),
        # 上（後）だけ：`ceiling_m` は変わらない。
        ([("FEW", 900.0), ("BKN", 4200.0), ("BKN", None)], "above"),
        ([("BKN", 4200.0), ("OVC", None), ("OVC", None)], "above"),
        # 下にも上にもあれば、下。
        ([("BKN", None), ("BKN", 3000.0), ("OVC", None)], "below"),
    ],
)
def test_skipped_layer_position(layers: list[Layer], expected: str) -> None:
    positions = eda.skipped_layer_position(_table(_row(layers)))

    assert list(positions) == [expected]


@pytest.mark.parametrize(
    "layers",
    [
        [],
        [("FEW", 900.0)],
        [("BKN", 300.0)],
        [("BKN", None)],
        [("SCT", None), ("BKN", 1500.0)],
        [("VV ", None)],
    ],
)
def test_skipped_layer_position_is_missing_when_nothing_was_skipped(layers: list[Layer]) -> None:
    positions = eda.skipped_layer_position(_table(_row(layers)))

    assert positions.isna().tolist() == [True]


def test_skipped_layer_position_matches_fixture_rows() -> None:
    table = parse_metar(metar_text("tokyo"))

    positions = eda.skipped_layer_position(table)

    expected: list[str | None] = []
    for report in table["metar"]:
        heights = [h for cover, h in reported_cloud_groups(report) if cover in ("BKN", "OVC")]
        known = [index for index, height in enumerate(heights) if height is not None]
        unknown = [index for index, height in enumerate(heights) if height is None]
        if not known or not unknown:
            expected.append(None)
        else:
            expected.append("below" if min(unknown) < min(known) else "above")
    assert [None if pd.isna(value) else value for value in positions] == expected
    assert "above" in expected


def test_eda_uses_the_shared_feature_functions() -> None:
    # 季節・現地の時・露点差・概算式は `ml/features.py`・`ml/baseline.py` に 1 つだけある。
    assert eda.season is features.season
    assert eda.local_hour is features.local_hour
    assert eda.dew_point_spread_c is features.dew_point_spread_c
    assert eda.rule_of_thumb_m is baseline.rule_of_thumb_m
    assert eda.SEASONS is features.SEASONS
    assert eda.RULE_OF_THUMB_M_PER_C == baseline.RULE_OF_THUMB_M_PER_C == 125.0


def test_eda_functions_do_not_modify_input() -> None:
    layers = _table(_row([("VV ", None)]), _row([("BKN", 300.0), ("BKN", None)]))
    times = _times("berlin", "2025-07-01T00:00:00Z")
    layers_before = layers.copy(deep=True)
    times_before = times.copy(deep=True)

    eda.ceiling_status(layers)
    eda.skipped_layer_position(layers)
    eda.local_hour(times)
    eda.season(times)

    pd.testing.assert_frame_equal(layers, layers_before)
    pd.testing.assert_frame_equal(times, times_before)
