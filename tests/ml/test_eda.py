import pandas as pd
import pytest

from ml import eda
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


@pytest.mark.parametrize(
    ("city", "time", "expected"),
    [
        # 東京は UTC+9：15:00 UTC で現地の日付が変わる。
        ("tokyo", "2025-02-28T14:59:00Z", "winter"),
        ("tokyo", "2025-02-28T15:00:00Z", "spring"),
        ("tokyo", "2025-05-31T15:00:00Z", "summer"),
        ("tokyo", "2025-08-31T15:00:00Z", "autumn"),
        ("tokyo", "2025-11-30T14:59:00Z", "autumn"),
        ("tokyo", "2025-11-30T15:00:00Z", "winter"),
        ("tokyo", "2025-12-31T15:00:00Z", "winter"),
        # ベルリンの夏は UTC+2：22:00 UTC で現地の日付が変わる。
        ("berlin", "2025-05-31T21:59:00Z", "spring"),
        ("berlin", "2025-05-31T22:00:00Z", "summer"),
        ("berlin", "2025-08-31T21:59:00Z", "summer"),
        ("berlin", "2025-08-31T22:00:00Z", "autumn"),
        # 冬は UTC+1：23:00 UTC で変わる。
        ("berlin", "2025-02-28T22:59:00Z", "winter"),
        ("berlin", "2025-02-28T23:00:00Z", "spring"),
        ("berlin", "2025-11-30T22:59:00Z", "autumn"),
        ("berlin", "2025-11-30T23:00:00Z", "winter"),
    ],
)
def test_season_from_local_month(city: str, time: str, expected: str) -> None:
    seasons = eda.season(_times(city, time))

    assert list(seasons) == [expected]
    assert expected in eda.SEASONS


@pytest.mark.parametrize(
    ("city", "time", "expected"),
    [
        ("tokyo", "2026-10-12T00:00:00Z", 9),
        ("tokyo", "2026-10-12T14:59:00Z", 23),
        ("tokyo", "2026-10-12T15:00:00Z", 0),
        # ベルリン：2026-10-12 は夏時間（UTC+2）、2026-12-21 は UTC+1（#7 のテストと同じ日）。
        ("berlin", "2026-10-12T22:00:00Z", 0),
        ("berlin", "2026-12-21T23:00:00Z", 0),
        # 夏時間が始まる日（2026-03-29）・終わる日（2026-10-25）の前後の日。
        ("berlin", "2026-03-28T12:00:00Z", 13),
        ("berlin", "2026-03-30T12:00:00Z", 14),
        ("berlin", "2026-10-24T12:00:00Z", 14),
        ("berlin", "2026-10-26T12:00:00Z", 13),
    ],
)
def test_local_hour_uses_city_timezone(city: str, time: str, expected: int) -> None:
    hours = eda.local_hour(_times(city, time))

    assert list(hours) == [expected]


def test_local_hour_and_season_handle_both_cities_and_keep_index() -> None:
    table = pd.concat(
        [
            _times("tokyo", "2025-02-28T15:00:00Z", "2025-07-01T00:00:00Z"),
            _times("berlin", "2025-02-28T15:00:00Z", "2025-07-01T00:00:00Z"),
        ]
    )
    table.index = pd.Index([13, 12, 11, 10])

    hours = eda.local_hour(table)
    seasons = eda.season(table)

    assert list(hours.index) == [13, 12, 11, 10]
    assert list(seasons.index) == [13, 12, 11, 10]
    assert list(hours) == [0, 9, 16, 2]
    assert list(seasons) == ["spring", "summer", "winter", "summer"]


@pytest.mark.parametrize("function", [eda.local_hour, eda.season])
def test_local_time_rejects_naive_or_non_utc_times(function: object) -> None:
    naive = _times("tokyo", "2025-01-15T00:00:00Z")
    naive["time"] = naive["time"].dt.tz_localize(None)
    local = _times("tokyo", "2025-01-15T00:00:00Z")
    local["time"] = local["time"].dt.tz_convert("Asia/Tokyo")

    for table in (naive, local):
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            function(table)  # type: ignore[operator]


@pytest.mark.parametrize("function", [eda.local_hour, eda.season])
def test_local_time_rejects_unknown_city(function: object) -> None:
    with pytest.raises(ValueError):
        function(_times("osaka", "2025-01-15T00:00:00Z"))  # type: ignore[operator]


def test_dew_point_spread_and_rule_of_thumb() -> None:
    temperature = pd.Series([20.0, 10.0, 5.0, None, 3.0], index=[5, 4, 3, 2, 1])
    dew_point = pd.Series([12.0, 10.0, 6.0, 1.0, None], index=[5, 4, 3, 2, 1])

    spread = eda.dew_point_spread_c(temperature, dew_point)
    estimate = eda.rule_of_thumb_m(spread)

    assert list(spread.index) == [5, 4, 3, 2, 1]
    # 露点のほうが高い行は、負のまま返す（0 に切り上げない）。欠損は欠損のまま。
    assert spread.iloc[:3].tolist() == [8.0, 0.0, -1.0]
    assert spread.iloc[3:].isna().tolist() == [True, True]
    assert estimate.iloc[:3].tolist() == [1000.0, 0.0, -125.0]
    assert estimate.iloc[3:].isna().tolist() == [True, True]


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
