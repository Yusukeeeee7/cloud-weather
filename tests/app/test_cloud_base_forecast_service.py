"""#15 24 時間の予報の雲底：`/weather` の hourly と同じ 24 時刻で予測する。"""

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from app.cities import CITIES, City
from app.errors import UpstreamError
from app.services import cloud_base_forecast
from app.services.forecast import build_hourly
from ml import model
from ml.features import FEATURE_NAMES
from tests.app.cloud_base_fakes import (
    CAP_M,
    ITEMS,
    expected_baseline_m,
    fake_model,
    row_of,
    training_features,
)
from tests.conftest import PAST_NOW, RawForecast, load_past_forecast

# PAST_NOW（2026-10-14T09:18Z）より後の最初の正時。
FIRST = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)


class SequenceBooster:
    """行ごとに決まった値を返す、モデルの代わり。"""

    def __init__(self, values: list[float]) -> None:
        self.values = values

    def predict(self, data: pd.DataFrame, **_: Any) -> Any:
        assert len(data) == len(self.values)
        return pd.Series(self.values, dtype="float64").to_numpy()


def _sequence_model(values: list[float]) -> model.CloudBaseModel:
    return model.CloudBaseModel(
        booster=SequenceBooster(values),  # type: ignore[arg-type]
        train_years=(2018,),
        model_version="fake-seq",
    )


def _times(raw: RawForecast, now: datetime) -> list[datetime]:
    fake, _ = fake_model(850.0)
    response = cloud_base_forecast.build_cloud_base_forecast_response(City.TOKYO, raw, now, fake)
    return [hour.time for hour in response.hourly]


def _with_value(raw: RawForecast, item: str, at: datetime, value: Any) -> RawForecast:
    changed = copy.deepcopy(raw)
    changed["hourly"][item][row_of(raw, at)] = value
    return changed


# --- F1：時刻は /weather の hourly と同じ ---


@pytest.mark.parametrize(
    "now",
    [
        PAST_NOW,
        datetime(2026, 10, 14, 10, 0, tzinfo=UTC),
        datetime(2026, 10, 14, 9, 59, 59, 999999, tzinfo=UTC),
        datetime(2026, 10, 14, 10, 0, 0, 1, tzinfo=UTC),
    ],
    ids=["fixture", "on-the-hour", "just-before", "just-after"],
)
@pytest.mark.parametrize("city", CITIES)
def test_forecast_times_match_weather_hourly(city: City, now: datetime) -> None:
    raw = load_past_forecast(city.value)
    fake, _ = fake_model(850.0)

    response = cloud_base_forecast.build_cloud_base_forecast_response(city, raw, now, fake)

    assert cloud_base_forecast.FORECAST_HOURS == 24
    assert [hour.time for hour in response.hourly] == [hour.time for hour in build_hourly(raw, now)]


def test_forecast_first_hour_after_now() -> None:
    raw = load_past_forecast("tokyo")

    assert _times(raw, PAST_NOW) == [FIRST + timedelta(hours=n) for n in range(24)]
    # 正時ちょうどなら、その時刻を含む。
    assert _times(raw, FIRST)[0] == FIRST


# --- F2・F3：モデルに渡す特徴量、1 回で 24 行 ---


@pytest.mark.parametrize("city", CITIES)
def test_forecast_rows_map_to_feature_columns(city: City) -> None:
    raw = load_past_forecast(city.value)
    fake, booster = fake_model(850.0)

    cloud_base_forecast.build_cloud_base_forecast_response(city, raw, PAST_NOW, fake)

    seen = booster.seen[0]
    assert list(seen.columns) == list(FEATURE_NAMES)
    expected = pd.concat(
        [training_features(city, raw, FIRST + timedelta(hours=n)) for n in range(24)],
        ignore_index=True,
    )
    pd.testing.assert_frame_equal(seen.reset_index(drop=True), expected, check_exact=True)


def test_forecast_predicts_24_rows_at_once() -> None:
    fake, booster = fake_model(850.0, model_version="fake-v7")

    response = cloud_base_forecast.build_cloud_base_forecast_response(
        City.TOKYO, load_past_forecast("tokyo"), PAST_NOW, fake
    )

    assert len(booster.seen) == 1
    assert len(booster.seen[0]) == 24
    assert response.city == "tokyo"
    assert response.model_version == "fake-v7"
    assert [hour.predicted_m for hour in response.hourly] == [850] * 24


# --- F4：丸めと範囲 ---


def test_forecast_rounds_and_limits_values() -> None:
    # 0.5 は切り上げる。負は 0、1,524 を超えたら 1,524。
    given = [-3.0, 0.49, 0.5, 700.4, 700.5, 701.5, 702.5, 1523.5, 1524.0, 1600.0]
    expected = [0, 0, 1, 700, 701, 702, 703, CAP_M, CAP_M, CAP_M]
    values = given + [850.0] * (24 - len(given))

    response = cloud_base_forecast.build_cloud_base_forecast_response(
        City.TOKYO, load_past_forecast("tokyo"), PAST_NOW, _sequence_model(values)
    )

    predicted = [hour.predicted_m for hour in response.hourly]
    assert predicted[: len(given)] == expected
    assert all(type(value) is int for value in predicted)


# --- F5：概算式 ---


@pytest.mark.parametrize("city", CITIES)
def test_forecast_baseline_matches_ml_baseline(city: City) -> None:
    raw = load_past_forecast(city.value)
    fake, _ = fake_model(850.0)

    response = cloud_base_forecast.build_cloud_base_forecast_response(city, raw, PAST_NOW, fake)

    for hour in response.hourly:
        assert hour.baseline_m == expected_baseline_m(raw, hour.time)
        assert type(hour.baseline_m) is int


# --- F6：範囲内の値の検証 ---


@pytest.mark.parametrize("item", ITEMS)
@pytest.mark.parametrize(
    "bad",
    [None, "12.5", True, float("nan"), float("inf")],
    ids=["null", "string", "bool", "nan", "inf"],
)
def test_forecast_invalid_value_in_window_is_upstream_error(item: str, bad: Any) -> None:
    raw = load_past_forecast("tokyo")
    # 範囲の最後の行（23 時間後）。
    changed = _with_value(raw, item, FIRST + timedelta(hours=23), bad)
    fake, booster = fake_model(850.0)

    with pytest.raises(UpstreamError):
        cloud_base_forecast.build_cloud_base_forecast_response(City.TOKYO, changed, PAST_NOW, fake)
    assert booster.seen == []


@pytest.mark.parametrize("item", ITEMS)
def test_forecast_ignores_null_outside_window(item: str) -> None:
    raw = load_past_forecast("tokyo")
    changed = _with_value(raw, item, FIRST - timedelta(hours=1), None)
    changed = _with_value(changed, item, FIRST + timedelta(hours=24), None)
    fake, _ = fake_model(850.0)

    response = cloud_base_forecast.build_cloud_base_forecast_response(
        City.TOKYO, changed, PAST_NOW, fake
    )

    assert len(response.hourly) == 24


@pytest.mark.parametrize("item", ["time", *ITEMS])
def test_forecast_missing_item_is_upstream_error(item: str) -> None:
    raw = copy.deepcopy(load_past_forecast("tokyo"))
    del raw["hourly"][item]
    fake, _ = fake_model(850.0)

    with pytest.raises(UpstreamError):
        cloud_base_forecast.build_cloud_base_forecast_response(City.TOKYO, raw, PAST_NOW, fake)


@pytest.mark.parametrize("item", ITEMS)
def test_forecast_column_of_different_length_is_upstream_error(item: str) -> None:
    raw = copy.deepcopy(load_past_forecast("tokyo"))
    raw["hourly"][item] = raw["hourly"][item][:-1]
    fake, _ = fake_model(850.0)

    with pytest.raises(UpstreamError):
        cloud_base_forecast.build_cloud_base_forecast_response(City.TOKYO, raw, PAST_NOW, fake)


# --- F7：単位 ---


@pytest.mark.parametrize("item", ["time", *ITEMS])
def test_forecast_unexpected_unit_is_upstream_error(item: str) -> None:
    raw = copy.deepcopy(load_past_forecast("tokyo"))
    raw["hourly_units"][item] = "unexpected"
    fake, _ = fake_model(850.0)

    with pytest.raises(UpstreamError):
        cloud_base_forecast.build_cloud_base_forecast_response(City.TOKYO, raw, PAST_NOW, fake)


@pytest.mark.parametrize("item", ["time", *ITEMS])
def test_forecast_missing_unit_is_upstream_error(item: str) -> None:
    raw = copy.deepcopy(load_past_forecast("tokyo"))
    del raw["hourly_units"][item]
    fake, _ = fake_model(850.0)

    with pytest.raises(UpstreamError):
        cloud_base_forecast.build_cloud_base_forecast_response(City.TOKYO, raw, PAST_NOW, fake)


# --- F8：行が足りない、1 時間おきでない ---


def test_forecast_not_enough_rows_is_upstream_error() -> None:
    raw = load_past_forecast("tokyo")
    last = datetime.fromtimestamp(raw["hourly"]["time"][-1], UTC)
    fake, _ = fake_model(850.0)

    # 最後の行の 23 時間前の直後なら、24 件目が最後の行。そこより後は足りない。
    ok = cloud_base_forecast.build_cloud_base_forecast_response(
        City.TOKYO, raw, last - timedelta(hours=23), fake
    )
    assert ok.hourly[-1].time == last
    with pytest.raises(UpstreamError):
        cloud_base_forecast.build_cloud_base_forecast_response(
            City.TOKYO, raw, last - timedelta(hours=23) + timedelta(seconds=1), fake
        )


def test_forecast_non_consecutive_times_is_upstream_error() -> None:
    raw = load_past_forecast("tokyo")
    at = FIRST + timedelta(hours=12)
    changed = _with_value(raw, "time", at, int(at.timestamp()) + 1800)
    fake, _ = fake_model(850.0)

    with pytest.raises(UpstreamError):
        cloud_base_forecast.build_cloud_base_forecast_response(City.TOKYO, changed, PAST_NOW, fake)


def test_forecast_input_is_not_modified() -> None:
    raw = load_past_forecast("tokyo")
    before = copy.deepcopy(raw)
    fake, _ = fake_model(850.0)

    cloud_base_forecast.build_cloud_base_forecast_response(City.TOKYO, raw, PAST_NOW, fake)

    assert raw == before


def test_forecast_converts_other_timezones_to_utc() -> None:
    from zoneinfo import ZoneInfo

    local = PAST_NOW.astimezone(ZoneInfo(CITIES[City.BERLIN].timezone))

    assert _times(load_past_forecast("tokyo"), local)[0] == FIRST
