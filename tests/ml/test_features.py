"""`tests/ml/test_eda.py` から移したテスト（関数を `ml/features.py` に移したため）。"""

import math

import pandas as pd
import pytest

from app.cities import CITIES, City
from app.services import solar
from ml import features
from tests.ml.tables import WEATHER_COLUMNS, sample_observations, times, weather_table


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


# docs/plans/11-train-evaluate.md「特徴量」。
# docs/spec.md「9. 特徴量」の候補と、前の 1 時間の降水量。
EXPECTED_FEATURE_NAMES = [
    "temperature_c",
    "dew_point_c",
    "relative_humidity",
    "pressure_msl_hpa",
    "wind_speed_ms",
    "dew_point_spread_c",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "local_hour_sin",
    "local_hour_cos",
    "day_of_year_sin",
    "day_of_year_cos",
    "solar_elevation_deg",
    "city_code",
    "precipitation_mm",
]


def _points(table: pd.DataFrame, name: str) -> list[tuple[float, float]]:
    return list(zip(table[f"{name}_sin"], table[f"{name}_cos"], strict=True))


def test_features_have_fixed_names_and_order() -> None:
    table = weather_table("tokyo", "2025-01-15T00:00:00Z", "2025-01-15T01:00:00Z")
    table.index = pd.Index([7, 3])

    result = features.features(table)

    assert list(features.FEATURE_NAMES) == EXPECTED_FEATURE_NAMES
    assert list(result.columns) == EXPECTED_FEATURE_NAMES
    assert list(result.index) == [7, 3]
    assert all(pd.api.types.is_numeric_dtype(dtype) for dtype in result.dtypes)
    assert not result.isna().any(axis=None)


def test_features_pass_weather_columns_through() -> None:
    table = weather_table(
        "berlin", "2025-01-15T00:00:00Z", "2025-01-15T01:00:00Z", "2025-01-15T02:00:00Z"
    )
    table.loc[1, "pressure_msl_hpa"] = None

    result = features.features(table)

    for name in WEATHER_COLUMNS:
        pd.testing.assert_series_equal(result[name], table[name].astype("float64"))
    expected = features.dew_point_spread_c(table["temperature_c"], table["dew_point_c"])
    assert result["dew_point_spread_c"].tolist() == expected.tolist()
    # 欠損は埋めずに、そのまま渡す。
    assert result["pressure_msl_hpa"].isna().tolist() == [False, True, False]


@pytest.mark.parametrize(
    ("time", "sine", "cosine"),
    [
        # 東京（UTC+9）の現地の 0・6・12・18 時。
        ("2025-01-15T15:00:00Z", 0.0, 1.0),
        ("2025-01-15T21:00:00Z", 1.0, 0.0),
        ("2025-01-15T03:00:00Z", 0.0, -1.0),
        ("2025-01-15T09:00:00Z", -1.0, 0.0),
    ],
)
def test_local_hour_is_cyclic(time: str, sine: float, cosine: float) -> None:
    result = features.features(weather_table("tokyo", time))

    assert result["local_hour_sin"].iloc[0] == pytest.approx(sine, abs=1e-9)
    assert result["local_hour_cos"].iloc[0] == pytest.approx(cosine, abs=1e-9)


def test_local_hour_wraps_around_midnight() -> None:
    # 東京の現地の 23・0・1 時。23 時と 0 時は、0 時と 1 時と同じだけ離れている。
    table = weather_table(
        "tokyo", "2025-01-15T14:00:00Z", "2025-01-15T15:00:00Z", "2025-01-15T16:00:00Z"
    )

    before, midnight, after = _points(features.features(table), "local_hour")

    assert math.dist(before, midnight) == pytest.approx(math.dist(midnight, after))


def test_day_of_year_is_cyclic_and_uses_local_date() -> None:
    # 東京では 15:00 UTC に現地の日付が変わる：現地の 1/1（1 日目）、1/2（2 日目）、1/2。
    table = weather_table(
        "tokyo", "2025-01-01T14:00:00Z", "2025-01-01T15:00:00Z", "2025-01-02T14:00:00Z"
    )

    result = features.features(table)

    # 1 年（365.25 日）で 1 周する。
    angles = [2 * math.pi * day / 365.25 for day in (1, 2, 2)]
    assert result["day_of_year_sin"].tolist() == pytest.approx([math.sin(a) for a in angles])
    assert result["day_of_year_cos"].tolist() == pytest.approx([math.cos(a) for a in angles])


def test_day_of_year_wraps_around_new_year() -> None:
    # ベルリンの現地の 12/31・1/1・1/3。年をまたぐ 1 日は、2 日離れた日より近い。
    table = weather_table(
        "berlin", "2025-12-31T12:00:00Z", "2026-01-01T12:00:00Z", "2026-01-03T12:00:00Z"
    )

    result = features.features(table)
    last_day, first_day, third_day = _points(result, "day_of_year")

    assert math.dist(last_day, first_day) < math.dist(first_day, third_day)
    for name in ("day_of_year_sin", "day_of_year_cos"):
        assert result[name].between(-1.0, 1.0).all()


def test_solar_elevation_matches_solar_module() -> None:
    observations = sample_observations()

    result = features.features(observations)

    assert len(result) == len(observations) > 0
    for (_, row), value in zip(observations.iterrows(), result["solar_elevation_deg"], strict=True):
        info = CITIES[City(row["city"])]
        expected = solar.solar_elevation_deg(
            info.latitude, info.longitude, row["time"].to_pydatetime()
        )
        assert value == pytest.approx(expected)


def test_solar_elevation_uses_the_city_location() -> None:
    time = "2025-01-15T03:00:00Z"

    tokyo = features.features(weather_table("tokyo", time))["solar_elevation_deg"].iloc[0]
    berlin = features.features(weather_table("berlin", time))["solar_elevation_deg"].iloc[0]

    # 東京は昼、ベルリンは夜明け前。
    assert tokyo > 0 > berlin


@pytest.mark.parametrize(
    ("city", "noon", "midnight"),
    [
        # 現地の 12 時と 0 時（東京は UTC+9、ベルリンの 1 月は UTC+1）。
        ("tokyo", "2025-01-15T03:00:00Z", "2025-01-15T15:00:00Z"),
        ("berlin", "2025-01-15T11:00:00Z", "2025-01-15T23:00:00Z"),
    ],
)
def test_solar_elevation_is_positive_at_local_noon_and_negative_at_midnight(
    city: str, noon: str, midnight: str
) -> None:
    elevation = features.features(weather_table(city, noon, midnight))["solar_elevation_deg"]

    assert elevation.iloc[0] > 0
    assert elevation.iloc[1] < 0


def test_city_code_follows_city_order() -> None:
    table = pd.concat(
        [
            weather_table("berlin", "2025-01-15T00:00:00Z"),
            weather_table("tokyo", "2025-01-15T00:00:00Z"),
        ],
        ignore_index=True,
    )

    codes = features.features(table)["city_code"]

    assert [city.value for city in City] == ["tokyo", "berlin"]
    assert codes.tolist() == [1, 0]


def test_features_do_not_need_metar_columns() -> None:
    observations = sample_observations()
    weather_only = observations[["city", "time", *WEATHER_COLUMNS]]

    assert "metar" in observations.columns
    pd.testing.assert_frame_equal(features.features(observations), features.features(weather_only))


def test_features_ignore_other_rows() -> None:
    table = pd.concat(
        [
            weather_table("tokyo", "2025-01-15T00:00:00Z", "2025-01-15T01:00:00Z"),
            weather_table("berlin", "2025-01-15T00:00:00Z", "2025-01-15T01:00:00Z"),
        ],
        ignore_index=True,
    )
    later = weather_table("tokyo", "2025-06-01T00:00:00Z", "2025-06-01T01:00:00Z")
    later.index = pd.Index([98, 99])
    # 後の時刻の行を足し、行の順を逆にする。
    extended = pd.concat([later, table.iloc[::-1]])

    result = features.features(extended)

    pd.testing.assert_frame_equal(result.loc[table.index], features.features(table))


def test_features_reject_bad_input() -> None:
    good = weather_table("tokyo", "2025-01-15T00:00:00Z")
    unknown_city = good.assign(city="osaka")
    naive = good.assign(time=good["time"].dt.tz_localize(None))
    local = good.assign(time=good["time"].dt.tz_convert("Asia/Tokyo"))
    missing_column = good.drop(columns=["pressure_msl_hpa"])

    for table in (unknown_city, naive, local, missing_column):
        with pytest.raises(ValueError):
            features.features(table)


def test_features_do_not_modify_input() -> None:
    table = weather_table("tokyo", "2025-01-15T00:00:00Z", "2025-01-15T01:00:00Z")
    before = table.copy(deep=True)

    features.features(table)

    pd.testing.assert_frame_equal(table, before)
