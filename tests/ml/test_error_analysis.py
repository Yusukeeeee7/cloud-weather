import json

import pandas as pd
import pytest

from ml import error_analysis
from tests.ml.tables import meters, times

# docs/spec.md「9. 目的変数」：上限は 1,524 m。
CAP_M = 1524.0
# docs/plans/16-error-analysis.md の質問 2：帯の境目は、下の帯に入れる。
BANDS = ("0_300", "300_600", "600_1000", "1000_1524")
DIRECTIONS = ("at_cap", "too_high", "too_low", "exact")
SUMMARY_KEYS = {
    "n_below_cap",
    "mae_below_cap_m",
    "bias_below_cap_m",
    *(f"n_{name}" for name in DIRECTIONS),
    *(f"abs_error_{name}_m" for name in DIRECTIONS),
}
GROUPINGS = {
    "overall",
    "by_city",
    "by_city_band",
    "by_city_season",
    "by_city_season_band",
    "by_city_hour_band",
    "by_city_change",
}


def test_height_band_names_each_band() -> None:
    assert error_analysis.HEIGHT_BANDS == BANDS

    result = error_analysis.height_band(meters(150.0, 450.0, 800.0, 1200.0))

    assert list(result) == list(BANDS)


def test_height_band_boundaries() -> None:
    result = error_analysis.height_band(meters(0.0, 300.0, 301.0, 600.0, 601.0, 1000.0, 1001.0))

    assert list(result) == [
        "0_300",
        "0_300",
        "300_600",
        "300_600",
        "600_1000",
        "600_1000",
        "1000_1524",
    ]
    # 上限のすぐ下は、最も高い帯。
    assert list(error_analysis.height_band(meters(1523.0))) == ["1000_1524"]


def test_height_band_is_missing_for_cap_and_missing_target() -> None:
    result = error_analysis.height_band(meters(CAP_M, None, 100.0))

    assert list(result.isna()) == [True, True, False]


def test_height_band_keeps_index_and_does_not_modify_input() -> None:
    target = pd.Series([100.0, CAP_M, 700.0], index=[7, 3, 5])
    before = target.copy()

    result = error_analysis.height_band(target)

    assert list(result.index) == [7, 3, 5]
    assert result[7] == "0_300"
    assert result[5] == "600_1000"
    pd.testing.assert_series_equal(target, before)


def test_direction_too_high_too_low_exact() -> None:
    assert error_analysis.DIRECTIONS == DIRECTIONS

    result = error_analysis.direction(meters(500.0, 500.0, 500.0), meters(600.0, 400.0, 500.0))

    assert list(result) == ["too_high", "too_low", "exact"]


def test_direction_at_cap_when_prediction_is_cap() -> None:
    # 予測がちょうど上限 ＝ 低い天井を見逃した。上限のすぐ下は「高すぎ」。
    result = error_analysis.direction(meters(500.0, 500.0), meters(CAP_M, 1523.0))

    assert list(result) == ["at_cap", "too_high"]


def test_direction_is_missing_for_cap_and_missing_target() -> None:
    # 正解のない行の予測は、欠損でもよい。
    result = error_analysis.direction(
        meters(CAP_M, None, None, 500.0), meters(800.0, 800.0, None, 800.0)
    )

    assert list(result.isna()) == [True, True, True, False]


def test_direction_rejects_mismatched_index_and_missing_prediction() -> None:
    target = pd.Series([100.0, 200.0], index=[1, 2])

    for predicted in (
        pd.Series([100.0, 200.0], index=[2, 1]),
        pd.Series([100.0, 200.0], index=[1, 3]),
        pd.Series([100.0], index=[1]),
    ):
        with pytest.raises(ValueError, match="same index"):
            error_analysis.direction(target, predicted)
    with pytest.raises(ValueError, match="missing prediction"):
        error_analysis.direction(meters(100.0, 200.0), meters(110.0, None))


def test_summarize_counts_only_rows_below_cap() -> None:
    # 上限の行（差 1,000）と、正解のない行は数えない。差は 50・150 → 平均 100。
    result = error_analysis.summarize(
        meters(100.0, 400.0, CAP_M, None), meters(150.0, 250.0, 524.0, 9999.0)
    )

    assert set(result) == SUMMARY_KEYS
    assert result["n_below_cap"] == 2
    assert result["mae_below_cap_m"] == 100.0


def test_summarize_bias_is_signed() -> None:
    # 予測 − 正解：+300・−100 → 平均 +100（高すぎが正）。MAE は 200。
    result = error_analysis.summarize(meters(100.0, 400.0), meters(400.0, 300.0))

    assert result["bias_below_cap_m"] == 100.0
    assert result["mae_below_cap_m"] == 200.0
    # すべて低すぎなら負。
    assert error_analysis.summarize(meters(400.0), meters(300.0))["bias_below_cap_m"] == -100.0


def test_summarize_direction_counts_and_error_sums() -> None:
    # 差：+1,024（見逃し）、+100・+200（高すぎ）、−50（低すぎ）、0（同じ）。上限の行は数えない。
    target = meters(500.0, 500.0, 500.0, 500.0, 500.0, CAP_M)
    predicted = meters(CAP_M, 600.0, 700.0, 450.0, 500.0, 900.0)

    result = error_analysis.summarize(target, predicted)

    assert [result[f"n_{name}"] for name in DIRECTIONS] == [1, 2, 1, 1]
    assert [result[f"abs_error_{name}_m"] for name in DIRECTIONS] == [1024.0, 300.0, 50.0, 0.0]
    assert sum(result[f"n_{name}"] for name in DIRECTIONS) == result["n_below_cap"] == 5
    # 誤差の合計の合計は 1,374 ＝ MAE（274.8）× 行数（5）。
    assert sum(result[f"abs_error_{name}_m"] for name in DIRECTIONS) == 1374.0
    assert result["mae_below_cap_m"] == pytest.approx(274.8)


def test_summarize_empty() -> None:
    for target, predicted in (
        (meters(), meters()),
        (meters(CAP_M, None), meters(800.0, None)),
    ):
        result = error_analysis.summarize(target, predicted)

        assert result["n_below_cap"] == 0
        assert result["mae_below_cap_m"] is None
        assert result["bias_below_cap_m"] is None
        assert [result[f"n_{name}"] for name in DIRECTIONS] == [0, 0, 0, 0]
        assert [result[f"abs_error_{name}_m"] for name in DIRECTIONS] == [0.0, 0.0, 0.0, 0.0]


def _two_cities() -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """東京 5 行・ベルリン 3 行（2024 年）。

    東京：現地 1 月 15 日の 9・10・11 時と、7 月 2 日の 5・6 時（UTC+9）。
    ベルリン：現地 1 月 15 日の 1・2・3 時（UTC+1）。2 行目は正解なし、3 行目は上限。
    """
    observations = pd.concat(
        [
            times(
                "tokyo",
                "2024-01-15T00:00:00Z",
                "2024-01-15T01:00:00Z",
                "2024-01-15T02:00:00Z",
                "2024-07-01T20:00:00Z",
                "2024-07-01T21:00:00Z",
            ),
            times("berlin", "2024-01-15T00:00:00Z", "2024-01-15T01:00:00Z", "2024-01-15T02:00:00Z"),
        ],
        ignore_index=True,
    )
    target = meters(200.0, 200.0, 500.0, 1000.0, 900.0, 1200.0, None, CAP_M)
    # 東京の差：+50、+1,324（見逃し）、−50、+100、0。ベルリンの差：−200。
    predicted = meters(250.0, CAP_M, 450.0, 1100.0, 900.0, 1000.0, None, 800.0)
    return observations, target, predicted


def test_summarize_by_groups_rows() -> None:
    observations, target, predicted = _two_cities()

    table = error_analysis.summarize_by(target, predicted, observations[["city"]])

    # 組の順は値の順。
    assert list(table.columns) == ["city", *error_analysis.SUMMARY]
    assert list(table["city"]) == ["berlin", "tokyo"]
    assert list(table["n_below_cap"]) == [1, 5]
    # 東京：差の合計 1,524 ÷ 5 行。
    assert list(table["mae_below_cap_m"]) == [200.0, pytest.approx(304.8)]
    assert list(table["n_at_cap"]) == [0, 1]
    for row in table.to_dict("records"):
        rows = (observations["city"] == row.pop("city")).to_numpy()
        assert row == error_analysis.summarize(target[rows], predicted[rows])


def test_summarize_by_rejects_missing_key_and_mismatched_index() -> None:
    observations, target, predicted = _two_cities()
    keys = observations[["city"]].copy()
    keys.loc[1, "city"] = None

    with pytest.raises(ValueError, match="missing key"):
        error_analysis.summarize_by(target, predicted, keys)
    with pytest.raises(ValueError, match="same index"):
        error_analysis.summarize_by(target, predicted, observations[["city"]].iloc[:4])
    with pytest.raises(ValueError, match="missing prediction"):
        error_analysis.summarize_by(target, meters(*[None] * 8), observations[["city"]])


def test_ceiling_change_same_lower_higher() -> None:
    assert error_analysis.CHANGES == ("same", "lower", "higher", "unknown")
    observations = times(
        "tokyo",
        "2024-01-15T00:00:00Z",
        "2024-01-15T01:00:00Z",
        "2024-01-15T02:00:00Z",
        "2024-01-15T03:00:00Z",
        "2024-01-15T04:00:00Z",
    )

    # 上限の行も「1 時間前の正解」として使う（上限 → 900 は「下がった」）。
    result = error_analysis.ceiling_change(observations, meters(500.0, 500.0, 300.0, CAP_M, 900.0))

    assert list(result)[1:] == ["same", "lower", "higher", "lower"]


def test_ceiling_change_unknown_without_previous_hour() -> None:
    observations = times(
        "tokyo",
        "2024-01-15T00:00:00Z",
        "2024-01-15T02:00:00Z",
        "2024-01-15T03:00:00Z",
        "2024-01-15T04:00:00Z",
        "2024-01-15T05:00:00Z",
    )

    result = error_analysis.ceiling_change(observations, meters(500.0, 500.0, None, 500.0, None))

    # 最初の行、時刻が飛んだ行、1 時間前の正解がない行、その行の正解がない行。
    assert list(result) == ["unknown", "unknown", "unknown", "unknown", "unknown"]


def test_ceiling_change_does_not_mix_cities() -> None:
    observations = pd.concat(
        [
            times("tokyo", "2024-01-15T00:00:00Z", "2024-01-15T01:00:00Z"),
            times("berlin", "2024-01-15T01:00:00Z", "2024-01-15T02:00:00Z"),
        ],
        ignore_index=True,
    )
    target = meters(500.0, 700.0, 300.0, 300.0)

    result = error_analysis.ceiling_change(observations, target)

    # ベルリンの 1 行目の「1 時間前」は、東京の 00:00（500）ではない。
    assert list(result) == ["unknown", "higher", "unknown", "same"]

    # 行の順を変えても、行の番号ごとの答えは同じ。
    order = [3, 1, 2, 0]
    shuffled = error_analysis.ceiling_change(observations.loc[order], target.loc[order])

    assert list(shuffled.index) == order
    assert shuffled.to_dict() == result.to_dict()
    with pytest.raises(ValueError, match="same index"):
        error_analysis.ceiling_change(observations, target.iloc[:3])


def test_report_has_all_groupings_for_each_prediction() -> None:
    observations, target, predicted = _two_cities()
    always_cap = pd.Series(CAP_M, index=target.index)

    result = error_analysis.report(
        observations, target, {"model": predicted, "rule_of_thumb": always_cap}
    )

    assert list(result) == ["model", "rule_of_thumb"]
    for part in result.values():
        assert set(part) == GROUPINGS
        assert set(part["overall"]) == SUMMARY_KEYS
        assert sorted(part["by_city"]) == ["berlin", "tokyo"]
        for city in ("berlin", "tokyo"):
            # 行のない組も、行数 0 で入る。
            assert list(part["by_city_band"][city]) == list(BANDS)
            assert list(part["by_city_season"][city]) == ["winter", "spring", "summer", "autumn"]
            for bands in part["by_city_season_band"][city].values():
                assert list(bands) == list(BANDS)
            assert list(part["by_city_hour_band"][city]) == [
                "night",
                "morning",
                "afternoon",
                "evening",
            ]
            assert list(part["by_city_change"][city]) == ["same", "lower", "higher", "unknown"]

    model = result["model"]
    assert model["overall"]["n_below_cap"] == 6
    assert model["by_city"]["tokyo"]["n_below_cap"] == 5
    assert model["by_city"]["tokyo"]["n_at_cap"] == 1
    assert model["by_city"]["berlin"]["n_too_low"] == 1
    tokyo_bands = model["by_city_band"]["tokyo"]
    assert [tokyo_bands[band]["n_below_cap"] for band in BANDS] == [2, 1, 2, 0]
    # 0〜300 m：差は 50・1,324 → 平均 687。
    assert tokyo_bands["0_300"]["mae_below_cap_m"] == 687.0
    assert tokyo_bands["1000_1524"]["mae_below_cap_m"] is None
    tokyo_seasons = model["by_city_season"]["tokyo"]
    assert [tokyo_seasons[name]["n_below_cap"] for name in tokyo_seasons] == [3, 0, 2, 0]
    assert model["by_city_season_band"]["tokyo"]["summer"]["600_1000"]["n_below_cap"] == 2
    assert model["by_city_season_band"]["berlin"]["winter"]["1000_1524"]["n_below_cap"] == 1
    # 東京の現地 5 時は夜、6 時は朝。ベルリンの現地 1 時は夜。
    tokyo_hours = model["by_city_hour_band"]["tokyo"]
    assert [tokyo_hours[name]["n_below_cap"] for name in tokyo_hours] == [1, 4, 0, 0]
    assert model["by_city_hour_band"]["berlin"]["night"]["n_below_cap"] == 1
    # 東京：同じ 1（見逃した行）、下がった 1、上がった 1、分からない 2（各日の最初の行）。
    tokyo_changes = model["by_city_change"]["tokyo"]
    assert [tokyo_changes[name]["n_below_cap"] for name in tokyo_changes] == [1, 1, 1, 2]
    assert tokyo_changes["same"]["n_at_cap"] == 1
    # 比べる相手（いつも上限）は、すべて見逃し。
    assert result["rule_of_thumb"]["overall"]["n_at_cap"] == 6


def test_report_is_json_serializable_and_rounded() -> None:
    observations, target, predicted = _two_cities()

    result = error_analysis.report(observations, target, {"model": predicted})
    text = json.dumps(result, allow_nan=False)

    assert json.loads(text) == result
    winter = result["model"]["by_city_season"]["tokyo"]["winter"]
    # 差は 50・1,324・50 → 平均 474.666…、偏りは（50 + 1,324 − 50）÷ 3 ＝ 441.333…。
    assert winter["mae_below_cap_m"] == 474.67
    assert winter["bias_below_cap_m"] == 441.33
    assert winter["abs_error_at_cap_m"] == 1324.0
    assert isinstance(winter["n_below_cap"], int)


def test_error_analysis_does_not_modify_input() -> None:
    observations, target, predicted = _two_cities()
    before = (observations.copy(deep=True), target.copy(), predicted.copy())

    error_analysis.direction(target, predicted)
    error_analysis.summarize(target, predicted)
    error_analysis.summarize_by(target, predicted, observations[["city"]])
    error_analysis.ceiling_change(observations, target)
    error_analysis.report(observations, target, {"model": predicted})

    pd.testing.assert_frame_equal(observations, before[0])
    pd.testing.assert_series_equal(target, before[1])
    pd.testing.assert_series_equal(predicted, before[2])


@pytest.mark.parametrize(
    ("time", "expected"),
    [
        # 東京（UTC+9）の現地 5・6 時、11・12 時、17・18 時、23・0 時。
        ("2024-01-14T20:00:00Z", "night"),
        ("2024-01-14T21:00:00Z", "morning"),
        ("2024-01-15T02:00:00Z", "morning"),
        ("2024-01-15T03:00:00Z", "afternoon"),
        ("2024-01-15T08:00:00Z", "afternoon"),
        ("2024-01-15T09:00:00Z", "evening"),
        ("2024-01-15T14:00:00Z", "evening"),
        ("2024-01-15T15:00:00Z", "night"),
    ],
)
def test_report_hour_band_boundaries(time: str, expected: str) -> None:
    result = error_analysis.report(times("tokyo", time), meters(500.0), {"model": meters(600.0)})

    hours = result["model"]["by_city_hour_band"]["tokyo"]
    assert [name for name in hours if hours[name]["n_below_cap"] == 1] == [expected]


def test_report_on_empty_input_is_json_serializable() -> None:
    result = error_analysis.report(times("tokyo"), meters(), {"model": meters()})

    assert set(result["model"]) == GROUPINGS
    assert result["model"]["overall"]["n_below_cap"] == 0
    assert result["model"]["overall"]["mae_below_cap_m"] is None
    assert result["model"]["by_city"] == {}
    assert result["model"]["by_city_change"] == {}
    json.dumps(result, allow_nan=False)


def test_ceiling_change_rejects_duplicate_city_and_time() -> None:
    # 同じ都市・同じ時刻の行が 2 つあると、「1 時間前の正解」が 1 つに決まらない。
    observations = times(
        "tokyo", "2024-01-15T00:00:00Z", "2024-01-15T00:00:00Z", "2024-01-15T01:00:00Z"
    )

    with pytest.raises(ValueError, match="duplicate city and time"):
        error_analysis.ceiling_change(observations, meters(500.0, 600.0, 700.0))
