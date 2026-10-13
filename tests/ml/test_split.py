import pandas as pd
import pytest

from ml import split
from tests.ml.tables import times


@pytest.mark.parametrize(
    ("time", "expected"),
    [
        # docs/spec.md「9. 分割と評価」：学習 2018〜2023、検証 2024、テスト 2025（年は UTC）。
        ("2018-01-01T00:00:00Z", "train"),
        ("2023-12-31T23:00:00Z", "train"),
        ("2024-01-01T00:00:00Z", "validation"),
        ("2024-12-31T23:00:00Z", "validation"),
        ("2025-01-01T00:00:00Z", "test"),
        ("2025-12-31T23:00:00Z", "test"),
    ],
)
def test_split_by_utc_year(time: str, expected: str) -> None:
    # 東京では、UTC の 12 月 31 日 15:00 から現地の日付が翌年になる。年は UTC で区切る。
    for city in ("tokyo", "berlin"):
        assert list(split.split(times(city, time))) == [expected]


@pytest.mark.parametrize("time", ["2017-12-31T23:00:00Z", "2026-01-01T00:00:00Z"])
def test_split_is_missing_outside_the_period(time: str) -> None:
    assert split.split(times("tokyo", time)).isna().tolist() == [True]


def test_split_years_follow_spec() -> None:
    assert split.SPLIT_YEARS == {
        "train": (2018, 2019, 2020, 2021, 2022, 2023),
        "validation": (2024,),
        "test": (2025,),
    }


def test_split_keeps_index_and_does_not_modify_input() -> None:
    table = times("berlin", "2025-06-01T00:00:00Z", "2024-06-01T00:00:00Z", "2020-06-01T00:00:00Z")
    table.index = pd.Index([30, 20, 10])
    before = table.copy(deep=True)

    labels = split.split(table)

    assert list(labels.index) == [30, 20, 10]
    assert labels.name == "split"
    assert list(labels) == ["test", "validation", "train"]
    pd.testing.assert_frame_equal(table, before)


def test_split_rejects_naive_or_non_utc_times() -> None:
    naive = times("tokyo", "2025-01-15T00:00:00Z")
    naive["time"] = naive["time"].dt.tz_localize(None)
    local = times("tokyo", "2025-01-15T00:00:00Z")
    local["time"] = local["time"].dt.tz_convert("Asia/Tokyo")

    for table in (naive, local):
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            split.split(table)


def test_short_train_years_follow_spec() -> None:
    # docs/spec.md「9. 分割と評価」：学習を 2021〜2023（3 年）にした場合と比べる。
    assert split.TRAIN_YEARS_SHORT == (2021, 2022, 2023)


@pytest.mark.parametrize(
    ("time", "expected"),
    [
        ("2020-12-31T23:00:00Z", False),
        ("2021-01-01T00:00:00Z", True),
        ("2023-12-31T23:00:00Z", True),
        ("2024-01-01T00:00:00Z", False),
        ("2025-06-01T00:00:00Z", False),
    ],
)
def test_rows_in_years_selects_only_those_years(time: str, expected: bool) -> None:
    # 年は UTC（東京では、UTC の 12 月 31 日 15:00 から現地の日付が翌年になる）。
    for city in ("tokyo", "berlin"):
        rows = split.rows_in_years(times(city, time), split.TRAIN_YEARS_SHORT)

        assert rows.tolist() == [expected]


def test_rows_in_years_keeps_index_and_does_not_modify_input() -> None:
    table = times("berlin", "2025-06-01T00:00:00Z", "2022-06-01T00:00:00Z", "2020-06-01T00:00:00Z")
    table.index = pd.Index([30, 20, 10])
    before = table.copy(deep=True)

    rows = split.rows_in_years(table, (2020, 2025))

    assert list(rows.index) == [30, 20, 10]
    assert rows.tolist() == [True, False, True]
    assert rows.dtype == bool
    pd.testing.assert_frame_equal(table, before)


def test_rows_in_years_rejects_naive_or_non_utc_times() -> None:
    naive = times("tokyo", "2025-01-15T00:00:00Z")
    naive["time"] = naive["time"].dt.tz_localize(None)
    local = times("tokyo", "2025-01-15T00:00:00Z")
    local["time"] = local["time"].dt.tz_convert("Asia/Tokyo")

    for table in (naive, local):
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            split.rows_in_years(table, (2025,))
