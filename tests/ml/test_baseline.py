import pandas as pd

from ml import baseline, features


def test_rule_of_thumb_is_125_times_spread() -> None:
    # `tests/ml/test_eda.py` から移した（概算式の部分。中身は変えていない）。
    temperature = pd.Series([20.0, 10.0, 5.0, None, 3.0], index=[5, 4, 3, 2, 1])
    dew_point = pd.Series([12.0, 10.0, 6.0, 1.0, None], index=[5, 4, 3, 2, 1])

    spread = features.dew_point_spread_c(temperature, dew_point)
    estimate = baseline.rule_of_thumb_m(spread)

    assert estimate.iloc[:3].tolist() == [1000.0, 0.0, -125.0]
    assert estimate.iloc[3:].isna().tolist() == [True, True]


def test_baseline_is_125_times_spread() -> None:
    # docs/spec.md「9. ベースライン」：125 × (気温 − 露点) [m]。
    temperature = pd.Series([20.0, 10.0, 6.5], index=[3, 2, 1])
    dew_point = pd.Series([12.0, 9.0, 6.5], index=[3, 2, 1])

    estimate = baseline.baseline_m(temperature, dew_point)

    assert list(estimate.index) == [3, 2, 1]
    assert estimate.name == "baseline_m"
    assert estimate.tolist() == [1000.0, 125.0, 0.0]


def test_baseline_is_clipped_to_zero_and_cap() -> None:
    temperature = pd.Series([5.0, 30.0, 22.192, None, 3.0])
    dew_point = pd.Series([6.0, 10.0, 10.0, 1.0, None])

    estimate = baseline.baseline_m(temperature, dew_point)

    # 露点のほうが高い（差が負）→ 0。上限（1,524 m）を超える → 上限。ちょうど上限（差 12.192 ℃）。
    assert estimate.iloc[:2].tolist() == [0.0, 1524.0]
    assert round(float(estimate.iloc[2]), 6) == 1524.0
    # 欠損は欠損のまま（0 や上限にしない）。
    assert estimate.iloc[3:].isna().tolist() == [True, True]


def test_baseline_does_not_modify_input() -> None:
    temperature = pd.Series([5.0, 30.0])
    dew_point = pd.Series([6.0, 10.0])
    before = (temperature.copy(), dew_point.copy())

    baseline.baseline_m(temperature, dew_point)

    pd.testing.assert_series_equal(temperature, before[0])
    pd.testing.assert_series_equal(dew_point, before[1])
