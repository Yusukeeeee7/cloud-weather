import json

import pandas as pd
import pytest

from ml import evaluate, features
from tests.ml.tables import meters, times

# docs/spec.md「9. 目的変数」：上限は 1,524 m。
CAP_M = 1524.0


def test_mae_on_small_input() -> None:
    # 差は 10・20・0 → 平均 10。
    assert evaluate.mae(meters(100.0, 200.0, CAP_M), meters(110.0, 180.0, CAP_M)) == 10.0


def test_mae_uses_absolute_differences() -> None:
    # 差は +30・−30 → 平均 30（打ち消し合って 0 にならない）。
    assert evaluate.mae(meters(100.0, 100.0), meters(130.0, 70.0)) == 30.0


def test_evaluate_on_small_input() -> None:
    result = evaluate.evaluate(meters(100.0, 200.0, CAP_M), meters(110.0, 180.0, CAP_M))

    assert result == {
        "n": 3,
        "mae_m": 10.0,
        "n_below_cap": 2,
        "mae_below_cap_m": 15.0,
        "below_predicted_below": 2,
        "below_predicted_cap": 0,
        "cap_predicted_below": 0,
        "cap_predicted_cap": 1,
        "below_cap_accuracy": 1.0,
    }


def test_evaluate_excludes_rows_without_target() -> None:
    # 正解のない行（学習・評価から除く行）は数えない。その行の予測は、欠損でもよい。
    result = evaluate.evaluate(meters(100.0, None, 200.0, None), meters(110.0, 9999.0, 180.0, None))

    assert result["n"] == 2
    assert result["mae_m"] == 15.0


def test_evaluate_rejects_missing_prediction() -> None:
    # 正解のある行の予測が欠損なら、黙って除かない。
    with pytest.raises(ValueError, match="missing prediction"):
        evaluate.evaluate(meters(100.0, 200.0), meters(110.0, None))
    with pytest.raises(ValueError, match="missing prediction"):
        evaluate.mae(meters(100.0, 200.0), meters(110.0, None))


def test_evaluate_rejects_misaligned_index() -> None:
    target = pd.Series([100.0, 200.0], index=[1, 2])

    for predicted in (
        pd.Series([100.0, 200.0], index=[2, 1]),
        pd.Series([100.0, 200.0], index=[1, 3]),
        pd.Series([100.0], index=[1]),
    ):
        with pytest.raises(ValueError, match="same index"):
            evaluate.evaluate(target, predicted)
        with pytest.raises(ValueError, match="same index"):
            evaluate.mae(target, predicted)


def test_evaluate_below_cap_mae_uses_only_rows_below_cap() -> None:
    # 正解がちょうど上限の行（差 1,000）は、上限より下の MAE に入らない。
    result = evaluate.evaluate(meters(100.0, CAP_M), meters(150.0, 524.0))

    assert result["n"] == 2
    assert result["mae_m"] == 525.0
    assert result["n_below_cap"] == 1
    assert result["mae_below_cap_m"] == 50.0


def test_evaluate_below_cap_mae_is_none_without_rows_below_cap() -> None:
    result = evaluate.evaluate(meters(CAP_M, CAP_M), meters(CAP_M, 1000.0))

    assert result["n_below_cap"] == 0
    assert result["mae_below_cap_m"] is None
    assert result["mae_m"] == 262.0


def test_evaluate_counts_below_cap_hits_and_misses() -> None:
    target = meters(100.0, 100.0, CAP_M, CAP_M, CAP_M)
    # 予測がちょうど上限は「上限より下ではない」。上限を超える予測も同じ。
    predicted = meters(500.0, CAP_M, 1000.0, CAP_M, 2000.0)

    result = evaluate.evaluate(target, predicted)

    assert result["below_predicted_below"] == 1
    assert result["below_predicted_cap"] == 1
    assert result["cap_predicted_below"] == 1
    assert result["cap_predicted_cap"] == 2
    # 5 行のうち 3 行が当たり。
    assert result["below_cap_accuracy"] == 0.6


def test_evaluate_on_empty_input() -> None:
    for target, predicted in (
        (meters(), meters()),
        (meters(None, None), meters(100.0, None)),
    ):
        result = evaluate.evaluate(target, predicted)

        assert result == {
            "n": 0,
            "mae_m": None,
            "n_below_cap": 0,
            "mae_below_cap_m": None,
            "below_predicted_below": 0,
            "below_predicted_cap": 0,
            "cap_predicted_below": 0,
            "cap_predicted_cap": 0,
            "below_cap_accuracy": None,
        }
        assert evaluate.mae(target, predicted) is None


def _two_cities() -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """東京 3 行・ベルリン 2 行。東京の 3 行目は、UTC では 2 月、現地では 3 月 1 日。"""
    observations = pd.concat(
        [
            times("tokyo", "2025-01-15T00:00:00Z", "2025-02-28T14:00:00Z", "2025-02-28T15:00:00Z"),
            times("berlin", "2025-01-15T00:00:00Z", "2025-07-01T00:00:00Z"),
        ],
        ignore_index=True,
    )
    target = meters(100.0, 200.0, 300.0, CAP_M, 400.0)
    predicted = meters(110.0, 230.0, 350.0, CAP_M, 1524.0)
    return observations, target, predicted


def test_evaluate_by_city() -> None:
    observations, target, predicted = _two_cities()

    table = evaluate.evaluate_by(target, predicted, observations[["city"]])

    assert list(table["city"]) == ["berlin", "tokyo"]
    assert list(table["n"]) == [2, 3]
    assert int(table["n"].sum()) == evaluate.evaluate(target, predicted)["n"]
    # 東京：差は 10・30・50 → 平均 30。ベルリン：差は 0・1,124 → 平均 562。
    assert list(table["mae_m"]) == [562.0, 30.0]
    assert list(table["n_below_cap"]) == [1, 3]
    assert list(table["below_predicted_cap"]) == [1, 0]


def test_evaluate_by_city_and_season() -> None:
    observations, target, predicted = _two_cities()
    keys = observations[["city"]].assign(season=features.season(observations))

    table = evaluate.evaluate_by(target, predicted, keys)

    groups = {(row.city, row.season): (row.n, row.mae_m) for row in table.itertuples(index=False)}
    # 季節は現地の月：東京の UTC 2 月 28 日 15:00 は、現地の 3 月 1 日（春）。
    assert groups == {
        ("berlin", "summer"): (1, 1124.0),
        ("berlin", "winter"): (1, 0.0),
        ("tokyo", "spring"): (1, 50.0),
        ("tokyo", "winter"): (2, 20.0),
    }
    assert int(table["n"].sum()) == 5


def test_evaluate_by_rejects_misaligned_keys() -> None:
    observations, target, predicted = _two_cities()

    with pytest.raises(ValueError, match="same index"):
        evaluate.evaluate_by(target, predicted, observations[["city"]].iloc[:4])


def test_evaluate_by_rejects_missing_keys() -> None:
    # 組を作る列に欠損があると、その行が黙って集計から落ちる（件数の合計が全体と合わなくなる）。
    observations, target, predicted = _two_cities()
    keys = observations[["city"]].copy()
    keys.loc[1, "city"] = None

    with pytest.raises(ValueError, match="missing key"):
        evaluate.evaluate_by(target, predicted, keys)


def test_report_has_overall_city_and_season() -> None:
    observations, target, predicted = _two_cities()

    result = evaluate.report(observations, target, predicted)

    assert set(result) == {"overall", "by_city", "by_city_season"}
    assert result["overall"] == evaluate.evaluate(target, predicted)
    assert set(result["by_city"]) == {"tokyo", "berlin"}
    assert result["by_city"]["tokyo"]["n"] == 3
    assert result["by_city"]["tokyo"]["mae_m"] == 30.0
    assert set(result["by_city_season"]["tokyo"]) == {"winter", "spring"}
    assert result["by_city_season"]["berlin"]["summer"]["mae_m"] == 1124.0
    # ベルリンの冬は、上限より下の行がない。
    assert result["by_city_season"]["berlin"]["winter"]["mae_below_cap_m"] is None


def test_report_is_json_serializable() -> None:
    observations, target, predicted = _two_cities()
    # 割り切れない平均（差 10・20・20 → 16.666…）は、小数 2 桁に丸める。
    predicted = meters(110.0, 220.0, 320.0, CAP_M, 1524.0)

    result = evaluate.report(observations, target, predicted)
    text = json.dumps(result, allow_nan=False)

    assert json.loads(text) == result
    assert result["by_city"]["tokyo"]["mae_m"] == 16.67
    assert isinstance(result["by_city"]["tokyo"]["n"], int)


def test_report_on_empty_input_is_json_serializable() -> None:
    observations = times("tokyo")

    result = evaluate.report(observations, meters(), meters())

    assert result["overall"]["n"] == 0
    assert result["overall"]["mae_m"] is None
    assert result["by_city"] == {}
    assert result["by_city_season"] == {}
    json.dumps(result, allow_nan=False)


def test_evaluate_does_not_modify_input() -> None:
    observations, target, predicted = _two_cities()
    before = (observations.copy(deep=True), target.copy(), predicted.copy())

    evaluate.evaluate(target, predicted)
    evaluate.evaluate_by(target, predicted, observations[["city"]])
    evaluate.report(observations, target, predicted)

    pd.testing.assert_frame_equal(observations, before[0])
    pd.testing.assert_series_equal(target, before[1])
    pd.testing.assert_series_equal(predicted, before[2])
