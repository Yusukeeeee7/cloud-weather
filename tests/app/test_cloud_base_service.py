"""#12 推論API：hourly の 1 行から予測を作るところ（外部通信・キャッシュなし）。"""

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from app.cities import City
from app.errors import UpstreamError
from app.services import cloud_base
from ml import archive, model
from ml.features import FEATURE_NAMES, features
from tests.app.cloud_base_fakes import (
    CAP_M,
    ITEMS,
    expected_baseline_m,
    fake_model,
    row_of,
    training_features,
)
from tests.conftest import CLOUD_BASE_NOW, RawForecast, load_cloud_base_forecast

# CLOUD_BASE_NOW（14:16:30Z）以前の、最も近い正時。
VALID_AT = datetime(2026, 10, 13, 14, 0, tzinfo=UTC)
CITIES = [City.TOKYO, City.BERLIN]


def _raw(city: City) -> RawForecast:
    return load_cloud_base_forecast(city.value)


def _first_time(raw: RawForecast) -> datetime:
    return datetime.fromtimestamp(raw["hourly"]["time"][0], UTC)


def _last_time(raw: RawForecast) -> datetime:
    return datetime.fromtimestamp(raw["hourly"]["time"][-1], UTC)


def _with_value(raw: RawForecast, item: str, at: datetime, value: Any) -> RawForecast:
    changed = copy.deepcopy(raw)
    changed["hourly"][item][row_of(raw, at)] = value
    return changed


# --- 1〜3：どの時刻を予測するか ---


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 13, 13, 41, tzinfo=UTC), datetime(2026, 10, 13, 13, 0, tzinfo=UTC)),
        (datetime(2026, 10, 13, 13, 0, tzinfo=UTC), datetime(2026, 10, 13, 13, 0, tzinfo=UTC)),
        (
            datetime(2026, 10, 13, 13, 59, 59, 999999, tzinfo=UTC),
            datetime(2026, 10, 13, 13, 0, tzinfo=UTC),
        ),
        (datetime(2026, 10, 13, 14, 0, tzinfo=UTC), datetime(2026, 10, 13, 14, 0, tzinfo=UTC)),
        (datetime(2026, 10, 13, 0, 0, 1, tzinfo=UTC), datetime(2026, 10, 13, 0, 0, tzinfo=UTC)),
        (CLOUD_BASE_NOW, VALID_AT),
    ],
)
def test_valid_at_is_latest_hour_at_or_before_now(now: datetime, expected: datetime) -> None:
    result = cloud_base.valid_at(now)

    assert result == expected
    assert result.utcoffset() == timedelta(0)


def test_valid_at_converts_other_timezones_to_utc() -> None:
    # 30 分ずれたタイムゾーンの時刻を渡しても、UTC の正時で区切る。
    india = datetime(2026, 10, 13, 19, 40, tzinfo=UTC).astimezone(
        datetime.strptime("+0530", "%z").tzinfo
    )

    assert cloud_base.valid_at(india) == datetime(2026, 10, 13, 19, 0, tzinfo=UTC)


@pytest.mark.parametrize("city", CITIES)
@pytest.mark.parametrize("after", [timedelta(0), timedelta(minutes=59, seconds=59)])
def test_valid_at_can_be_first_row(city: City, after: timedelta) -> None:
    raw = _raw(city)
    first = _first_time(raw)
    fake, _ = fake_model(800.0)

    response = cloud_base.build_cloud_base_response(city, raw, first + after, fake)

    assert response.valid_at == first


@pytest.mark.parametrize("city", CITIES)
def test_valid_at_can_be_last_row(city: City) -> None:
    raw = _raw(city)
    last = _last_time(raw)
    fake, _ = fake_model(800.0)

    response = cloud_base.build_cloud_base_response(city, raw, last + timedelta(minutes=30), fake)

    assert response.valid_at == last


@pytest.mark.parametrize("city", CITIES)
def test_row_outside_hourly_times_is_upstream_error(city: City) -> None:
    raw = _raw(city)
    fake, booster = fake_model(800.0)
    before = _first_time(raw) - timedelta(seconds=1)
    after = _last_time(raw) + timedelta(hours=1)

    for now in (before, after):
        with pytest.raises(UpstreamError):
            cloud_base.build_cloud_base_response(city, raw, now, fake)
    assert booster.seen == []


# --- 4〜8：hourly の行を、特徴量の入力にする ---


@pytest.mark.parametrize("city", CITIES)
def test_input_row_maps_open_meteo_names_to_feature_columns(city: City) -> None:
    raw = _raw(city)
    row = row_of(raw, VALID_AT)

    table = cloud_base.input_row(city, raw, CLOUD_BASE_NOW)

    assert len(table) == 1
    assert table["city"].tolist() == [city.value]
    assert table["time"].tolist() == [pd.Timestamp(VALID_AT)]
    assert str(table["time"].dt.tz) == "UTC"
    for item in ITEMS:
        # 学習データを作るとき（ml/archive.py）と同じ対応で、列の名前を付ける。
        column, _ = archive.VARIABLES[item]
        assert table[column].tolist() == [float(raw["hourly"][item][row])], item
        assert table[column].dtype == "float64", item


@pytest.mark.parametrize("city", CITIES)
def test_input_row_gives_same_features_as_training_path(city: City) -> None:
    raw = _raw(city)

    made = features(cloud_base.input_row(city, raw, CLOUD_BASE_NOW))

    pd.testing.assert_frame_equal(
        made.reset_index(drop=True), training_features(city, raw, VALID_AT), check_exact=True
    )


@pytest.mark.parametrize("item", ITEMS)
@pytest.mark.parametrize("bad", [None, "12.5", True], ids=["null", "string", "bool"])
def test_invalid_hourly_value_is_upstream_error(item: str, bad: Any) -> None:
    raw = _with_value(_raw(City.TOKYO), item, VALID_AT, bad)
    fake, booster = fake_model(800.0)

    with pytest.raises(UpstreamError):
        cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)
    # 欠損のまま予測しない。
    assert booster.seen == []


@pytest.mark.parametrize("item", ITEMS)
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")], ids=str)
def test_nan_or_infinite_hourly_value_is_upstream_error(item: str, bad: float) -> None:
    # Python の JSON の読み込みは NaN・Infinity という書き方を受け付けるので、数値として届きうる。
    raw = _with_value(_raw(City.TOKYO), item, VALID_AT, bad)
    fake, booster = fake_model(800.0)

    with pytest.raises(UpstreamError):
        cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)
    assert booster.seen == []


@pytest.mark.parametrize("item", ITEMS)
def test_unexpected_hourly_unit_is_upstream_error(item: str) -> None:
    # 学習データを作るとき（ml/archive.py）と同じ単位でなければ、取り違えずにエラーにする。
    raw = _raw(City.TOKYO)
    assert raw["hourly_units"][item] == archive.VARIABLES[item][1]
    raw["hourly_units"][item] = "km/h"
    fake, booster = fake_model(800.0)

    with pytest.raises(UpstreamError):
        cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)
    assert booster.seen == []


@pytest.mark.parametrize("item", ["time", *ITEMS])
def test_missing_hourly_unit_is_upstream_error(item: str) -> None:
    raw = _raw(City.TOKYO)
    del raw["hourly_units"][item]
    fake, _ = fake_model(800.0)

    with pytest.raises(UpstreamError):
        cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)


@pytest.mark.parametrize("units", [None, [], "units"], ids=["null", "list", "str"])
def test_broken_hourly_units_section_is_upstream_error(units: Any) -> None:
    raw = _raw(City.TOKYO)
    raw["hourly_units"] = units
    fake, _ = fake_model(800.0)

    with pytest.raises(UpstreamError):
        cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)


def test_iso8601_time_format_is_upstream_error() -> None:
    # 時刻は UNIX 秒で受け取る決まり（timeformat=unixtime）。
    raw = _raw(City.TOKYO)
    raw["hourly_units"]["time"] = "iso8601"
    fake, _ = fake_model(800.0)

    with pytest.raises(UpstreamError):
        cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)


@pytest.mark.parametrize("item", ["time", *ITEMS])
def test_missing_hourly_item_is_upstream_error(item: str) -> None:
    raw = _raw(City.TOKYO)
    del raw["hourly"][item]
    fake, _ = fake_model(800.0)

    with pytest.raises(UpstreamError):
        cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)


@pytest.mark.parametrize("hourly", [None, [], "hourly", {}], ids=["null", "list", "str", "empty"])
def test_broken_hourly_section_is_upstream_error(hourly: Any) -> None:
    raw = _raw(City.TOKYO)
    raw["hourly"] = hourly
    fake, _ = fake_model(800.0)

    with pytest.raises(UpstreamError):
        cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)


@pytest.mark.parametrize("kind", [str, float])
def test_non_integer_hourly_time_is_upstream_error(kind: type) -> None:
    # 小数の UNIX 秒は、整数と等しいと判定されて行が選べてしまうので、型で落とす。
    raw = _raw(City.TOKYO)
    raw["hourly"]["time"] = [kind(value) for value in raw["hourly"]["time"]]
    fake, _ = fake_model(800.0)

    with pytest.raises(UpstreamError):
        cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)


def test_too_many_hourly_rows_is_upstream_error() -> None:
    # Open-Meteo の予報は最大 16 日（384 行）。それを超える応答は処理しない。
    raw = _raw(City.TOKYO)
    rows = len(raw["hourly"]["time"])
    extra = 16 * 24 + 1 - rows
    last = raw["hourly"]["time"][-1]
    for name, column in raw["hourly"].items():
        if name == "time":
            column.extend(last + 3600 * step for step in range(1, extra + 1))
        else:
            column.extend([column[-1]] * extra)
    fake, _ = fake_model(800.0)

    with pytest.raises(UpstreamError):
        cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)

    # ちょうど 16 日ぶんは受け付ける。
    for column in raw["hourly"].values():
        column.pop()
    response = cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)
    assert response.valid_at == VALID_AT


@pytest.mark.parametrize("item", ITEMS)
def test_null_in_other_rows_is_ignored(item: str) -> None:
    raw = _raw(City.TOKYO)
    plain, _ = fake_model(800.0)
    expected = cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, plain)
    # 使う行の前後と、いちばん先の時刻を null にする。
    for other in (VALID_AT - timedelta(hours=1), VALID_AT + timedelta(hours=1), _last_time(raw)):
        raw = _with_value(raw, item, other, None)
    fake, _ = fake_model(800.0)

    response = cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)

    assert response == expected


@pytest.mark.parametrize("item", ITEMS)
def test_hourly_columns_of_different_length_is_upstream_error(item: str) -> None:
    # 長さが違う列は、どの行がどの時刻か分からない（使う行が残っていてもエラー）。
    raw = _raw(City.TOKYO)
    raw["hourly"][item] = raw["hourly"][item][:-1]
    fake, _ = fake_model(800.0)

    with pytest.raises(UpstreamError):
        cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)


def test_input_is_not_modified() -> None:
    raw = _raw(City.TOKYO)
    before = copy.deepcopy(raw)
    fake, _ = fake_model(800.0)

    cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)

    assert raw == before


# --- 9〜13：予測とベースライン ---


@pytest.mark.parametrize("city", CITIES)
def test_predicted_m_comes_from_model_with_feature_columns_in_order(city: City) -> None:
    raw = _raw(city)
    fake, booster = fake_model(850.0, model_version="fake-v7")

    response = cloud_base.build_cloud_base_response(city, raw, CLOUD_BASE_NOW, fake)

    assert response.city == city.value
    assert response.valid_at == VALID_AT
    assert response.predicted_m == 850
    assert response.model_version == "fake-v7"
    assert len(booster.seen) == 1
    seen = booster.seen[0]
    assert list(seen.columns) == list(FEATURE_NAMES)
    pd.testing.assert_frame_equal(
        seen.reset_index(drop=True), training_features(city, raw, VALID_AT), check_exact=True
    )


def test_city_code_differs_between_cities() -> None:
    codes = {}
    for city in CITIES:
        fake, booster = fake_model(850.0)
        cloud_base.build_cloud_base_response(city, _raw(city), CLOUD_BASE_NOW, fake)
        codes[city] = booster.seen[0]["city_code"].tolist()

    assert codes == {City.TOKYO: [0], City.BERLIN: [1]}


@pytest.mark.parametrize("city", CITIES)
def test_predicted_m_matches_committed_model(city: City) -> None:
    # 何 m になるかの期待値は作らない。リポジトリのモデルを ml/ の関数で直接呼んだ値と比べる。
    raw = _raw(city)
    committed = model.load(cloud_base.MODEL_PATH)
    direct = model.predict_m(committed, training_features(city, raw, VALID_AT)).iloc[0]

    response = cloud_base.build_cloud_base_response(city, raw, CLOUD_BASE_NOW, committed)

    assert response.predicted_m == int(direct + 0.5)
    assert response.model_version == committed.model_version
    assert 0 <= response.predicted_m <= CAP_M


@pytest.mark.parametrize(
    ("value", "expected"),
    [(-50.0, 0), (0.0, 0), (99999.0, CAP_M), (1524.0, CAP_M), (1523.6, CAP_M)],
)
def test_predicted_m_is_within_zero_and_cap(value: float, expected: int) -> None:
    fake, _ = fake_model(value)

    response = cloud_base.build_cloud_base_response(
        City.TOKYO, _raw(City.TOKYO), CLOUD_BASE_NOW, fake
    )

    assert response.predicted_m == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    # 0.5 は切り上げる（偶数への丸めだと 700.5 → 700、702.5 → 702 になる）。
    [(700.4, 700), (700.5, 701), (701.5, 702), (702.5, 703), (0.49, 0), (0.5, 1)],
)
def test_predicted_m_is_rounded_half_up_to_integer(value: float, expected: int) -> None:
    fake, _ = fake_model(value)

    response = cloud_base.build_cloud_base_response(
        City.TOKYO, _raw(City.TOKYO), CLOUD_BASE_NOW, fake
    )

    assert response.predicted_m == expected
    assert type(response.predicted_m) is int


@pytest.mark.parametrize("city", CITIES)
@pytest.mark.parametrize("hours_later", [0, 1, 5, 24])
def test_baseline_m_follows_rule_of_thumb(city: City, hours_later: int) -> None:
    raw = _raw(city)
    now = CLOUD_BASE_NOW + timedelta(hours=hours_later)
    fake, _ = fake_model(850.0)

    response = cloud_base.build_cloud_base_response(city, raw, now, fake)

    at = VALID_AT + timedelta(hours=hours_later)
    assert response.valid_at == at
    assert response.baseline_m == expected_baseline_m(raw, at)
    assert type(response.baseline_m) is int


@pytest.mark.parametrize(
    ("temperature", "dew_point", "expected"),
    [
        # 露点のほうが高い（負）は 0。
        (10.0, 12.0, 0),
        (10.0, 10.0, 0),
        # 125 × 4 = 500。
        (14.0, 10.0, 500),
        # 125 × 12 = 1,500（上限より下）、125 × 13 = 1,625（上限に収める）。
        (22.0, 10.0, 1500),
        (23.0, 10.0, CAP_M),
        (40.0, 10.0, CAP_M),
        # 125 × 0.5 = 62.5 は切り上げて 63。
        (10.5, 10.0, 63),
    ],
)
def test_baseline_m_boundaries(temperature: float, dew_point: float, expected: int) -> None:
    raw = _with_value(_raw(City.TOKYO), "temperature_2m", VALID_AT, temperature)
    raw = _with_value(raw, "dew_point_2m", VALID_AT, dew_point)
    fake, _ = fake_model(850.0)

    response = cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)

    assert response.baseline_m == expected


def test_integer_values_from_open_meteo_are_accepted() -> None:
    # 小数の項目が、きりのよい値のときに整数で届いても受け付ける。
    raw = _with_value(_raw(City.TOKYO), "temperature_2m", VALID_AT, 14)
    raw = _with_value(raw, "dew_point_2m", VALID_AT, 10)
    fake, _ = fake_model(850.0)

    response = cloud_base.build_cloud_base_response(City.TOKYO, raw, CLOUD_BASE_NOW, fake)

    assert response.baseline_m == 500
