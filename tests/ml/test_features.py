"""`tests/ml/test_eda.py` から移したテスト（関数を `ml/features.py` に移したため）。"""

import pandas as pd
import pytest

from ml import features
from tests.ml.tables import times


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
    seasons = features.season(times(city, time))

    assert list(seasons) == [expected]
    assert expected in features.SEASONS


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
    hours = features.local_hour(times(city, time))

    assert list(hours) == [expected]


def test_local_hour_and_season_handle_both_cities_and_keep_index() -> None:
    table = pd.concat(
        [
            times("tokyo", "2025-02-28T15:00:00Z", "2025-07-01T00:00:00Z"),
            times("berlin", "2025-02-28T15:00:00Z", "2025-07-01T00:00:00Z"),
        ]
    )
    table.index = pd.Index([13, 12, 11, 10])

    hours = features.local_hour(table)
    seasons = features.season(table)

    assert list(hours.index) == [13, 12, 11, 10]
    assert list(seasons.index) == [13, 12, 11, 10]
    assert list(hours) == [0, 9, 16, 2]
    assert list(seasons) == ["spring", "summer", "winter", "summer"]


@pytest.mark.parametrize("function", [features.local_hour, features.season])
def test_local_time_rejects_naive_or_non_utc_times(function: object) -> None:
    naive = times("tokyo", "2025-01-15T00:00:00Z")
    naive["time"] = naive["time"].dt.tz_localize(None)
    local = times("tokyo", "2025-01-15T00:00:00Z")
    local["time"] = local["time"].dt.tz_convert("Asia/Tokyo")

    for table in (naive, local):
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            function(table)  # type: ignore[operator]


@pytest.mark.parametrize("function", [features.local_hour, features.season])
def test_local_time_rejects_unknown_city(function: object) -> None:
    with pytest.raises(ValueError):
        function(times("osaka", "2025-01-15T00:00:00Z"))  # type: ignore[operator]


def test_dew_point_spread() -> None:
    # 概算式の部分は `tests/ml/test_baseline.py` にある。
    temperature = pd.Series([20.0, 10.0, 5.0, None, 3.0], index=[5, 4, 3, 2, 1])
    dew_point = pd.Series([12.0, 10.0, 6.0, 1.0, None], index=[5, 4, 3, 2, 1])

    spread = features.dew_point_spread_c(temperature, dew_point)

    assert list(spread.index) == [5, 4, 3, 2, 1]
    # 露点のほうが高い行は、負のまま返す（0 に切り上げない）。欠損は欠損のまま。
    assert spread.iloc[:3].tolist() == [8.0, 0.0, -1.0]
    assert spread.iloc[3:].isna().tolist() == [True, True]
