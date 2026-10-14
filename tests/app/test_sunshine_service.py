"""#15 日差し：`/weather` の hourly と同じ 24 時刻の、日照時間と日射。

期待値は fixture の行から読む。
"""

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.cities import CITIES, City
from app.errors import UpstreamError
from app.services import sunshine
from app.services.forecast import MAX_HOURLY_ROWS, build_hourly
from tests.app.cloud_base_fakes import row_of
from tests.conftest import SUN_NOW, RawForecast, load_sun_forecast

ITEMS = ("sunshine_duration", "direct_radiation", "diffuse_radiation")
# SUN_NOW（2026-10-14T12:21Z）より後の最初の正時。
FIRST = datetime(2026, 10, 14, 13, 0, tzinfo=UTC)


def _with_value(raw: RawForecast, item: str, at: datetime, value: Any) -> RawForecast:
    changed = copy.deepcopy(raw)
    changed["hourly"][item][row_of(raw, at)] = value
    return changed


def _build(raw: RawForecast, now: datetime = SUN_NOW) -> Any:
    return sunshine.build_sunshine_response(City.TOKYO, raw, now)


# --- S2：時刻は /weather の hourly と同じ ---


@pytest.mark.parametrize(
    "now",
    [
        SUN_NOW,
        datetime(2026, 10, 14, 13, 0, tzinfo=UTC),
        datetime(2026, 10, 14, 12, 59, 59, 999999, tzinfo=UTC),
    ],
    ids=["fixture", "on-the-hour", "just-before"],
)
@pytest.mark.parametrize("city", CITIES)
def test_sunshine_times_match_weather_hourly(city: City, now: datetime) -> None:
    raw = load_sun_forecast(city.value)

    response = sunshine.build_sunshine_response(city, raw, now)

    assert response.city == city.value
    assert [hour.time for hour in response.hourly] == [hour.time for hour in build_hourly(raw, now)]


def test_sunshine_first_hour_after_now() -> None:
    response = _build(load_sun_forecast("tokyo"))

    assert [hour.time for hour in response.hourly] == [
        FIRST + timedelta(hours=n) for n in range(24)
    ]


# --- S3：値は fixture のまま ---


@pytest.mark.parametrize("city", CITIES)
def test_sunshine_values_come_from_fixture(city: City) -> None:
    raw = load_sun_forecast(city.value)

    response = sunshine.build_sunshine_response(city, raw, SUN_NOW)

    for hour in response.hourly:
        row = row_of(raw, hour.time)
        assert hour.sunshine_s == raw["hourly"]["sunshine_duration"][row]
        assert hour.direct_radiation_wm2 == raw["hourly"]["direct_radiation"][row]
        assert hour.diffuse_radiation_wm2 == raw["hourly"]["diffuse_radiation"][row]


def test_sunshine_keeps_fractional_seconds() -> None:
    # 丸めない（日の出・日の入りの行は、0〜3,600 の途中の小数になる）。
    raw = _with_value(load_sun_forecast("tokyo"), "sunshine_duration", FIRST, 566.56)

    assert _build(raw).hourly[0].sunshine_s == 566.56


# --- S4：範囲内の値の検証 ---


@pytest.mark.parametrize("item", ITEMS)
@pytest.mark.parametrize(
    "bad",
    [None, "12.5", True, float("nan"), float("inf")],
    ids=["null", "string", "bool", "nan", "inf"],
)
@pytest.mark.parametrize("at", [FIRST, FIRST + timedelta(hours=23)], ids=["first", "last"])
def test_sunshine_invalid_value_in_window_is_upstream_error(
    item: str, bad: Any, at: datetime
) -> None:
    changed = _with_value(load_sun_forecast("tokyo"), item, at, bad)

    with pytest.raises(UpstreamError):
        _build(changed)


@pytest.mark.parametrize("item", ITEMS)
def test_sunshine_ignores_null_outside_window(item: str) -> None:
    raw = _with_value(load_sun_forecast("tokyo"), item, FIRST - timedelta(hours=1), None)
    raw = _with_value(raw, item, FIRST + timedelta(hours=24), None)

    assert len(_build(raw).hourly) == 24


# --- S5：項目・行がない ---


@pytest.mark.parametrize("item", ["time", *ITEMS])
def test_sunshine_missing_item_is_upstream_error(item: str) -> None:
    raw = copy.deepcopy(load_sun_forecast("tokyo"))
    del raw["hourly"][item]

    with pytest.raises(UpstreamError):
        _build(raw)


@pytest.mark.parametrize("item", ITEMS)
def test_sunshine_column_of_different_length_is_upstream_error(item: str) -> None:
    raw = copy.deepcopy(load_sun_forecast("tokyo"))
    raw["hourly"][item] = raw["hourly"][item][:-1]

    with pytest.raises(UpstreamError):
        _build(raw)


@pytest.mark.parametrize("hourly", [None, [], "hourly", {}], ids=["null", "list", "str", "empty"])
def test_sunshine_broken_hourly_section_is_upstream_error(hourly: Any) -> None:
    raw = copy.deepcopy(load_sun_forecast("tokyo"))
    raw["hourly"] = hourly

    with pytest.raises(UpstreamError):
        _build(raw)


def test_sunshine_too_many_rows_is_upstream_error() -> None:
    # Open-Meteo の予報は最大 16 日（MAX_HOURLY_ROWS）。これを超える配列は処理しない。
    raw = copy.deepcopy(load_sun_forecast("tokyo"))
    first = raw["hourly"]["time"][0]
    rows = MAX_HOURLY_ROWS + 1
    raw["hourly"] = {
        "time": [first + 3600 * n for n in range(rows)],
        **{item: [100.0] * rows for item in ITEMS},
    }

    with pytest.raises(UpstreamError):
        _build(raw)


def test_sunshine_not_enough_rows_is_upstream_error() -> None:
    raw = load_sun_forecast("tokyo")
    last = datetime.fromtimestamp(raw["hourly"]["time"][-1], UTC)

    assert _build(raw, last - timedelta(hours=23)).hourly[-1].time == last
    with pytest.raises(UpstreamError):
        _build(raw, last - timedelta(hours=23) + timedelta(seconds=1))


def test_sunshine_non_consecutive_times_is_upstream_error() -> None:
    raw = load_sun_forecast("tokyo")
    at = FIRST + timedelta(hours=12)
    changed = _with_value(raw, "time", at, int(at.timestamp()) + 1800)

    with pytest.raises(UpstreamError):
        _build(changed)


@pytest.mark.parametrize("kind", [str, float])
def test_sunshine_non_integer_time_is_upstream_error(kind: type) -> None:
    raw = copy.deepcopy(load_sun_forecast("tokyo"))
    raw["hourly"]["time"] = [kind(value) for value in raw["hourly"]["time"]]

    with pytest.raises(UpstreamError):
        _build(raw)


def test_sunshine_input_is_not_modified() -> None:
    raw = load_sun_forecast("tokyo")
    before = copy.deepcopy(raw)

    _build(raw)

    assert raw == before
