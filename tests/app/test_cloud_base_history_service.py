"""#15 過去 24 時間の雲底：`/cloud-history` と同じ 24 時刻で予測する。"""

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from app.cities import CITIES, City
from app.errors import UpstreamError
from app.services import cloud_base_history
from app.services.cloud_history import build_cloud_history_response, history_times
from ml import model
from ml.features import FEATURE_NAMES
from tests.app.cloud_base_fakes import (
    CAP_M,
    ITEMS,
    SequenceBooster,
    expected_baseline_m,
    fake_model,
    row_of,
    training_features,
)
from tests.conftest import PAST_NOW, RawForecast, load_past_forecast, without_past_hours

# PAST_NOW（2026-10-14T09:18Z）以前の最も近い正時と、その 23 時間前。
LATEST = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
FIRST = LATEST - timedelta(hours=23)


def _build(raw: RawForecast, now: datetime, fake: model.CloudBaseModel | None = None) -> Any:
    if fake is None:
        fake, _ = fake_model(850.0)
    return cloud_base_history.build_cloud_base_history_response(City.TOKYO, raw, now, fake)


def _with_value(raw: RawForecast, item: str, at: datetime, value: Any) -> RawForecast:
    changed = copy.deepcopy(raw)
    changed["hourly"][item][row_of(raw, at)] = value
    return changed


# --- H1：時刻は /cloud-history と同じ ---


@pytest.mark.parametrize(
    "now",
    [
        PAST_NOW,
        datetime(2026, 10, 14, 13, 0, tzinfo=UTC),
        datetime(2026, 10, 14, 13, 59, 59, 999999, tzinfo=UTC),
    ],
    ids=["fixture", "on-the-hour", "just-before"],
)
@pytest.mark.parametrize("city", CITIES)
def test_history_times_match_cloud_history(city: City, now: datetime) -> None:
    raw = load_past_forecast(city.value)
    fake, _ = fake_model(850.0)

    response = cloud_base_history.build_cloud_base_history_response(city, raw, now, fake)

    times = [hour.time for hour in response.hourly]
    assert times == [hour.time for hour in build_cloud_history_response(city, raw, now).hourly]
    assert times == history_times(now)


def test_history_times_end_at_latest_past_hour() -> None:
    assert history_times(PAST_NOW) == [FIRST + timedelta(hours=n) for n in range(24)]


def test_history_converts_other_timezones_to_utc() -> None:
    from zoneinfo import ZoneInfo

    local = PAST_NOW.astimezone(ZoneInfo(CITIES[City.TOKYO].timezone))

    assert history_times(local)[-1] == LATEST


# --- H2：モデルに渡す特徴量、1 回で 24 行 ---


@pytest.mark.parametrize("city", CITIES)
def test_history_rows_map_to_feature_columns(city: City) -> None:
    raw = load_past_forecast(city.value)
    fake, booster = fake_model(850.0, model_version="fake-v7")

    response = cloud_base_history.build_cloud_base_history_response(city, raw, PAST_NOW, fake)

    assert response.city == city.value
    assert response.model_version == "fake-v7"
    assert len(booster.seen) == 1
    seen = booster.seen[0]
    assert list(seen.columns) == list(FEATURE_NAMES)
    expected = pd.concat(
        [training_features(city, raw, FIRST + timedelta(hours=n)) for n in range(24)],
        ignore_index=True,
    )
    pd.testing.assert_frame_equal(seen.reset_index(drop=True), expected, check_exact=True)
    assert [hour.predicted_m for hour in response.hourly] == [850] * 24


# --- H3：丸めと範囲 ---


def test_history_rounds_and_limits_values() -> None:
    given = [-3.0, 0.49, 0.5, 700.4, 700.5, 701.5, 702.5, 1523.5, 1524.0, 1600.0]
    expected = [0, 0, 1, 700, 701, 702, 703, CAP_M, CAP_M, CAP_M]
    fake = model.CloudBaseModel(
        booster=SequenceBooster(given + [850.0] * (24 - len(given))),  # type: ignore[arg-type]
        train_years=(2018,),
        model_version="fake-seq",
    )

    response = _build(load_past_forecast("tokyo"), PAST_NOW, fake)

    predicted = [hour.predicted_m for hour in response.hourly]
    assert predicted[: len(given)] == expected
    assert all(type(value) is int for value in predicted)


# --- H4：概算式 ---


@pytest.mark.parametrize("city", CITIES)
def test_history_baseline_matches_ml_baseline(city: City) -> None:
    raw = load_past_forecast(city.value)
    fake, _ = fake_model(850.0)

    response = cloud_base_history.build_cloud_base_history_response(city, raw, PAST_NOW, fake)

    for hour in response.hourly:
        assert hour.baseline_m == expected_baseline_m(raw, hour.time)


# --- H5：範囲内の値の検証 ---


@pytest.mark.parametrize("item", ITEMS)
@pytest.mark.parametrize(
    "bad",
    [None, "12.5", True, float("nan"), float("inf")],
    ids=["null", "string", "bool", "nan", "inf"],
)
@pytest.mark.parametrize("at", [FIRST, LATEST], ids=["first", "last"])
def test_history_invalid_value_in_window_is_upstream_error(
    item: str, bad: Any, at: datetime
) -> None:
    changed = _with_value(load_past_forecast("tokyo"), item, at, bad)
    fake, booster = fake_model(850.0)

    with pytest.raises(UpstreamError):
        _build(changed, PAST_NOW, fake)
    assert booster.seen == []


@pytest.mark.parametrize("item", ITEMS)
def test_history_ignores_null_outside_window(item: str) -> None:
    raw = load_past_forecast("tokyo")
    changed = _with_value(raw, item, FIRST - timedelta(hours=1), None)
    changed = _with_value(changed, item, LATEST + timedelta(hours=1), None)

    assert len(_build(changed, PAST_NOW).hourly) == 24


@pytest.mark.parametrize("item", ["time", *ITEMS])
def test_history_unexpected_unit_is_upstream_error(item: str) -> None:
    raw = copy.deepcopy(load_past_forecast("tokyo"))
    raw["hourly_units"][item] = "unexpected"

    with pytest.raises(UpstreamError):
        _build(raw, PAST_NOW)


@pytest.mark.parametrize("item", ["time", *ITEMS])
def test_history_missing_item_is_upstream_error(item: str) -> None:
    raw = copy.deepcopy(load_past_forecast("tokyo"))
    del raw["hourly"][item]

    with pytest.raises(UpstreamError):
        _build(raw, PAST_NOW)


# --- H6：過去の行がない ---


def test_history_missing_row_is_upstream_error() -> None:
    with pytest.raises(UpstreamError):
        _build(without_past_hours(load_past_forecast("tokyo")), PAST_NOW)


def test_history_can_start_at_first_row() -> None:
    raw = load_past_forecast("tokyo")
    first_row = datetime.fromtimestamp(raw["hourly"]["time"][0], UTC)

    ok = _build(raw, first_row + timedelta(hours=23, minutes=59))
    assert ok.hourly[0].time == first_row
    with pytest.raises(UpstreamError):
        _build(raw, first_row + timedelta(hours=22, minutes=59))


def test_history_non_consecutive_times_is_upstream_error() -> None:
    raw = load_past_forecast("tokyo")
    at = FIRST + timedelta(hours=12)
    changed = _with_value(raw, "time", at, int(at.timestamp()) + 1800)

    with pytest.raises(UpstreamError):
        _build(changed, PAST_NOW)


def test_history_input_is_not_modified() -> None:
    raw = load_past_forecast("tokyo")
    before = copy.deepcopy(raw)

    _build(raw, PAST_NOW)

    assert raw == before
