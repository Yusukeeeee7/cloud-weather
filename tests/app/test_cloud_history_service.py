"""#15 過去 24 時間の雲量：hourly から 24 件を選ぶ（期待値は fixture の行から読む）。"""

import copy
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.cities import CITIES, City
from app.errors import UpstreamError
from app.services.cloud_history import HISTORY_COUNT, build_cloud_history_response
from app.services.forecast import MAX_HOURLY_ROWS
from tests.conftest import PAST_NOW, RawForecast, load_past_forecast

CLOUD_ITEMS = ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high")
# PAST_NOW（2026-10-14T09:18Z）以前の最も近い正時。
LATEST = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def _row_of(raw: RawForecast, at: datetime) -> int:
    times: list[int] = raw["hourly"]["time"]
    return times.index(int(at.timestamp()))


def _first_time(raw: RawForecast) -> datetime:
    return datetime.fromtimestamp(raw["hourly"]["time"][0], UTC)


def _with_value(raw: RawForecast, item: str, row: int, value: Any) -> RawForecast:
    changed = copy.deepcopy(raw)
    changed["hourly"][item][row] = value
    return changed


def _times(response_hourly: list[Any]) -> list[datetime]:
    return [hour.time for hour in response_hourly]


# --- 2：24 件、最後が現在以前の最も近い正時 ---


@pytest.mark.parametrize("city", CITIES)
def test_history_returns_24_hours_ending_at_latest_past_hour(city: City) -> None:
    raw = load_past_forecast(city.value)

    response = build_cloud_history_response(city, raw, PAST_NOW)

    assert response.city == city.value
    assert HISTORY_COUNT == 24
    assert len(response.hourly) == 24
    expected_times = [LATEST - timedelta(hours=23 - n) for n in range(24)]
    assert _times(response.hourly) == expected_times
    for hour in response.hourly:
        row = _row_of(raw, hour.time)
        assert hour.cloud_cover.total == raw["hourly"]["cloud_cover"][row]
        assert hour.cloud_cover.low == raw["hourly"]["cloud_cover_low"][row]
        assert hour.cloud_cover.mid == raw["hourly"]["cloud_cover_mid"][row]
        assert hour.cloud_cover.high == raw["hourly"]["cloud_cover_high"][row]


# --- 3・4：境界 ---


@pytest.mark.parametrize("city", CITIES)
def test_history_on_the_hour_includes_that_hour(city: City) -> None:
    raw = load_past_forecast(city.value)
    on_the_hour = datetime(2026, 10, 14, 13, 0, tzinfo=UTC)

    response = build_cloud_history_response(city, raw, on_the_hour)

    assert response.hourly[-1].time == on_the_hour
    assert response.hourly[0].time == on_the_hour - timedelta(hours=23)


@pytest.mark.parametrize("city", CITIES)
def test_history_just_before_the_hour(city: City) -> None:
    raw = load_past_forecast(city.value)
    just_before = datetime(2026, 10, 14, 13, 59, 59, 999999, tzinfo=UTC)

    response = build_cloud_history_response(city, raw, just_before)

    assert response.hourly[-1].time == datetime(2026, 10, 14, 13, 0, tzinfo=UTC)


def test_history_converts_other_timezones_to_utc() -> None:
    raw = load_past_forecast("tokyo")
    # 2026-10-14T18:18+09:00 は 09:18Z。
    local = PAST_NOW.astimezone(ZoneInfo(CITIES[City.TOKYO].timezone))

    response = build_cloud_history_response(City.TOKYO, raw, local)

    assert response.hourly[-1].time == LATEST
    assert response.hourly[-1].time.utcoffset() == timedelta(0)


# --- 5：その時刻の行がない ---


@pytest.mark.parametrize("city", CITIES)
def test_history_can_start_at_first_row(city: City) -> None:
    raw = load_past_forecast(city.value)
    # 先頭の行の 23 時間後なら、先頭から 24 件ちょうど。
    now = _first_time(raw) + timedelta(hours=23, minutes=59)

    response = build_cloud_history_response(city, raw, now)

    assert response.hourly[0].time == _first_time(raw)


@pytest.mark.parametrize("city", CITIES)
def test_history_missing_row_is_upstream_error(city: City) -> None:
    raw = load_past_forecast(city.value)
    # 先頭の行の 22 時間後では、24 件目（いちばん古い時刻）が先頭より前になる。
    now = _first_time(raw) + timedelta(hours=22, minutes=59)

    with pytest.raises(UpstreamError):
        build_cloud_history_response(city, raw, now)


def test_history_after_last_row_is_upstream_error() -> None:
    raw = load_past_forecast("tokyo")
    last = datetime.fromtimestamp(raw["hourly"]["time"][-1], UTC)

    with pytest.raises(UpstreamError):
        build_cloud_history_response(City.TOKYO, raw, last + timedelta(hours=1))


# --- 6：雲量の欠け・null・型違い ---


@pytest.mark.parametrize("item", CLOUD_ITEMS)
@pytest.mark.parametrize(
    "bad", [None, "35", True, 35.5, float("nan")], ids=["null", "string", "bool", "float", "nan"]
)
@pytest.mark.parametrize("at", [LATEST, LATEST - timedelta(hours=23)], ids=["last", "first"])
def test_history_invalid_cloud_cover_is_upstream_error(item: str, bad: Any, at: datetime) -> None:
    raw = load_past_forecast("tokyo")
    changed = _with_value(raw, item, _row_of(raw, at), bad)

    with pytest.raises(UpstreamError):
        build_cloud_history_response(City.TOKYO, changed, PAST_NOW)


@pytest.mark.parametrize("item", CLOUD_ITEMS)
def test_history_ignores_null_outside_window(item: str) -> None:
    raw = load_past_forecast("tokyo")
    before = _row_of(raw, LATEST - timedelta(hours=24))
    after = _row_of(raw, LATEST + timedelta(hours=1))
    changed = _with_value(_with_value(raw, item, before, None), item, after, None)

    response = build_cloud_history_response(City.TOKYO, changed, PAST_NOW)

    assert len(response.hourly) == 24


@pytest.mark.parametrize("item", ["time", *CLOUD_ITEMS])
def test_history_missing_column_is_upstream_error(item: str) -> None:
    raw = copy.deepcopy(load_past_forecast("tokyo"))
    del raw["hourly"][item]

    with pytest.raises(UpstreamError):
        build_cloud_history_response(City.TOKYO, raw, PAST_NOW)


@pytest.mark.parametrize("item", CLOUD_ITEMS)
def test_history_column_of_different_length_is_upstream_error(item: str) -> None:
    raw = copy.deepcopy(load_past_forecast("tokyo"))
    raw["hourly"][item] = raw["hourly"][item][:-1]

    with pytest.raises(UpstreamError):
        build_cloud_history_response(City.TOKYO, raw, PAST_NOW)


def test_history_too_many_rows_is_upstream_error() -> None:
    # Open-Meteo の予報は最大 16 日（MAX_HOURLY_ROWS）。これを超える配列は処理しない。
    raw = copy.deepcopy(load_past_forecast("tokyo"))
    first = raw["hourly"]["time"][0]
    rows = MAX_HOURLY_ROWS + 1
    raw["hourly"] = {
        "time": [first + 3600 * n for n in range(rows)],
        **{item: [50] * rows for item in CLOUD_ITEMS},
    }

    with pytest.raises(UpstreamError):
        build_cloud_history_response(City.TOKYO, raw, PAST_NOW)


@pytest.mark.parametrize("hourly", [None, [], "hourly", {}], ids=["null", "list", "str", "empty"])
def test_history_broken_hourly_section_is_upstream_error(hourly: Any) -> None:
    raw = copy.deepcopy(load_past_forecast("tokyo"))
    raw["hourly"] = hourly

    with pytest.raises(UpstreamError):
        build_cloud_history_response(City.TOKYO, raw, PAST_NOW)


@pytest.mark.parametrize("kind", [str, float])
def test_history_non_integer_time_is_upstream_error(kind: type) -> None:
    raw = copy.deepcopy(load_past_forecast("tokyo"))
    raw["hourly"]["time"] = [kind(value) for value in raw["hourly"]["time"]]

    with pytest.raises(UpstreamError):
        build_cloud_history_response(City.TOKYO, raw, PAST_NOW)


# --- 7：時刻が 1 時間おきでない ---


def test_history_non_consecutive_times_is_upstream_error() -> None:
    raw = load_past_forecast("tokyo")
    middle = _row_of(raw, LATEST - timedelta(hours=12))
    shifted = raw["hourly"]["time"][middle] + 1800
    changed = _with_value(raw, "time", middle, shifted)

    with pytest.raises(UpstreamError):
        build_cloud_history_response(City.TOKYO, changed, PAST_NOW)


def test_history_input_is_not_modified() -> None:
    raw = load_past_forecast("tokyo")
    original = copy.deepcopy(raw)

    build_cloud_history_response(City.TOKYO, raw, PAST_NOW)

    assert raw == original
