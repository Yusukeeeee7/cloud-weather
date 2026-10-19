"""#25 気候の比較ページ：`ml/climate.py` の集計。表は手で書いた小さなもの。"""

import json
import math
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from ml import climate
from tests.solar_refs import usno_twilight


def _hours(city: str, start: str, count: int, **columns: list[object]) -> pd.DataFrame:
    """`start`（UTC）から 1 時間おきに `count` 行。列は全行ぶんの値の並び。"""
    table = pd.DataFrame(
        {
            "city": pd.Series([city] * count, dtype="str"),
            "time": pd.date_range(start, periods=count, freq="h", tz="UTC"),
        }
    )
    for name, values in columns.items():
        assert len(values) == count
        table[name] = values
    return table


def _tokyo_day(local_day: str, precipitation: list[float] | None = None) -> pd.DataFrame:
    """東京の現地の 1 日（24 行。UTC では前の日の 15 時から）。"""
    start = pd.Timestamp(local_day, tz="Asia/Tokyo").tz_convert("UTC")
    values = precipitation if precipitation is not None else [0.0] * 24
    return _hours("tokyo", str(start), 24, precipitation_mm=[*values])


def _wet_day(local_day: str, total_mm: float) -> pd.DataFrame:
    return _tokyo_day(local_day, [total_mm, *[0.0] * 23])


def _concat(*tables: pd.DataFrame) -> pd.DataFrame:
    return pd.concat(tables, ignore_index=True)


def _as_dict(table: pd.DataFrame, key: str, value: str) -> dict[object, object]:
    return dict(zip(table[key], table[value], strict=True))


# 1
def test_local_date_uses_city_timezone() -> None:
    tokyo = _hours("tokyo", "2025-01-01T14:00", 2)
    berlin_winter = _hours("berlin", "2025-01-01T22:00", 2)
    berlin_summer = _hours("berlin", "2025-07-01T21:00", 2)

    dates = climate.local_date(_concat(tokyo, berlin_winter, berlin_summer))

    assert list(dates) == [
        date(2025, 1, 1),
        date(2025, 1, 2),
        date(2025, 1, 1),
        date(2025, 1, 2),
        date(2025, 7, 1),
        date(2025, 7, 2),
    ]


def test_local_date_requires_utc() -> None:
    table = _hours("tokyo", "2025-01-01T00:00", 1)
    table["time"] = table["time"].dt.tz_localize(None)

    with pytest.raises(ValueError):
        climate.local_date(table)


# 2
def test_complete_days_drops_partial_days() -> None:
    full = _tokyo_day("2025-01-02")
    partial = _tokyo_day("2025-01-03").iloc[:23]

    kept = climate.complete_days(_concat(full, partial))

    assert set(kept["local_date"]) == {date(2025, 1, 2)}
    assert len(kept) == 24


# 3
def test_complete_days_dst_days() -> None:
    # ベルリンの夏時間の始まり（現地の 1 日が 23 時間）と終わり（25 時間）。
    spring = _hours("berlin", "2025-03-29T23:00", 23)
    autumn = _hours("berlin", "2025-10-25T22:00", 25)
    autumn_short = _hours("berlin", "2025-10-26T23:00", 24).iloc[:-1]

    kept = climate.complete_days(_concat(spring, autumn, autumn_short))

    assert set(kept["local_date"]) == {date(2025, 3, 30), date(2025, 10, 26)}


# 4
def test_monthly_temperature_metar_and_reanalysis() -> None:
    january = _hours(
        "tokyo",
        "2025-01-10T00:00",
        3,
        metar_temperature_c=[1.0, 3.0, None],
        temperature_c=[2.0, 4.0, 6.0],
    )
    february = _hours(
        "tokyo", "2025-02-10T00:00", 1, metar_temperature_c=[10.0], temperature_c=[20.0]
    )
    table = _concat(january, february)

    metar = climate.monthly_temperature_c(table, "metar")
    reanalysis = climate.monthly_temperature_c(table, "reanalysis")

    assert _as_dict(metar, "month", "temperature_c") == {1: 2.0, 2: 10.0}
    assert _as_dict(reanalysis, "month", "temperature_c") == {1: 4.0, 2: 20.0}
    assert set(metar["city"]) == {"tokyo"}


def test_monthly_temperature_uses_local_month() -> None:
    # UTC では 1 月 31 日 15 時、東京では 2 月 1 日 0 時。
    table = _hours("tokyo", "2025-01-31T15:00", 1, metar_temperature_c=[5.0], temperature_c=[5.0])

    result = climate.monthly_temperature_c(table, "metar")

    assert _as_dict(result, "month", "temperature_c") == {2: 5.0}


# 追加 2 の③：露点
def test_monthly_dew_point_skips_missing() -> None:
    table = _concat(
        _hours("tokyo", "2025-01-10T00:00", 3, metar_dew_point_c=[-2.0, 4.0, None]),
        _hours("tokyo", "2025-02-10T00:00", 1, metar_dew_point_c=[7.5]),
    )

    result = climate.monthly_dew_point_c(table)

    assert _as_dict(result, "month", "dew_point_c") == {1: 1.0, 2: 7.5}
    assert set(result["city"]) == {"tokyo"}


def test_monthly_dew_point_drops_month_without_values() -> None:
    # 2 月の行はあるが、露点がすべて欠けている。0 ℃ ではなく、その月の値なし（JSON では null）。
    table = _concat(
        _hours("tokyo", "2025-01-10T00:00", 1, metar_dew_point_c=[2.0]),
        _hours("tokyo", "2025-02-10T00:00", 2, metar_dew_point_c=[None, None]),
    )

    result = climate.monthly_dew_point_c(table)

    assert _as_dict(result, "month", "dew_point_c") == {1: 2.0}


def test_monthly_dew_point_uses_local_month() -> None:
    # UTC では 1 月 31 日 15 時、東京では 2 月 1 日 0 時。
    table = _hours("tokyo", "2025-01-31T15:00", 1, metar_dew_point_c=[3.0])

    result = climate.monthly_dew_point_c(table)

    assert _as_dict(result, "month", "dew_point_c") == {2: 3.0}


# 追加 2 の④：風速
def test_monthly_wind_speed_skips_missing() -> None:
    table = _concat(
        _hours("tokyo", "2025-01-10T00:00", 3, wind_speed_ms=[2.0, 5.0, None]),
        _hours("tokyo", "2025-02-10T00:00", 1, wind_speed_ms=[4.5]),
        _hours("tokyo", "2025-03-10T00:00", 1, wind_speed_ms=[None]),
    )

    result = climate.monthly_wind_speed_ms(table)

    assert _as_dict(result, "month", "wind_speed_ms") == {1: 3.5, 2: 4.5}
    assert set(result["city"]) == {"tokyo"}


def test_monthly_wind_speed_uses_local_month() -> None:
    # UTC では 1 月 31 日 15 時、東京では 2 月 1 日 0 時。
    table = _hours("tokyo", "2025-01-31T15:00", 1, wind_speed_ms=[3.0])

    result = climate.monthly_wind_speed_ms(table)

    assert _as_dict(result, "month", "wind_speed_ms") == {2: 3.0}


# 5
def test_monthly_temperature_rejects_unknown_source() -> None:
    table = _hours("tokyo", "2025-01-10T00:00", 1, metar_temperature_c=[1.0], temperature_c=[1.0])

    with pytest.raises(ValueError):
        climate.monthly_temperature_c(table, "observed")


# 6
def test_daily_precipitation_sums_local_day() -> None:
    day = _tokyo_day("2025-01-02", [0.5, *[0.0] * 22, 0.25])
    # 前の日の最後の 1 時間だけ（そろっていない日なので捨てる）。
    before = _hours("tokyo", "2025-01-01T14:00", 1, precipitation_mm=[9.0])

    daily = climate.daily_precipitation_mm(_concat(before, day))

    assert _as_dict(daily, "local_date", "precipitation_mm") == {date(2025, 1, 2): 0.75}


def test_daily_precipitation_drops_day_with_missing_value() -> None:
    day = _tokyo_day("2025-01-02", [None, *[0.0] * 23])  # type: ignore[list-item]

    daily = climate.daily_precipitation_mm(day)

    assert daily.empty


# 7
def test_wet_days_threshold_is_inclusive() -> None:
    table = _concat(_wet_day("2025-01-10", 0.99), _wet_day("2025-01-11", 1.0))

    wet = climate.monthly_wet_days(table)

    assert _as_dict(wet, "month", "days") == {1: 1.0}


# 8
def test_wet_days_average_per_year() -> None:
    table = _concat(
        _wet_day("2024-01-10", 1.0),
        _wet_day("2024-01-11", 2.0),
        _wet_day("2025-01-10", 1.5),
        _wet_day("2025-01-11", 0.0),
    )

    wet = climate.monthly_wet_days(table)

    assert _as_dict(wet, "month", "days") == {1: 1.5}


# 9
def test_yearly_precipitation_counts_complete_days() -> None:
    table = _concat(
        _wet_day("2024-06-01", 1.0),
        _wet_day("2024-06-02", 2.0),
        _wet_day("2025-06-01", 0.5),
        _tokyo_day("2025-06-02").iloc[:20],
    )

    yearly = climate.yearly_precipitation_mm(table)

    assert _as_dict(yearly, "year", "precipitation_mm") == {2024: 3.0, 2025: 0.5}
    assert _as_dict(yearly, "year", "complete_days") == {2024: 2, 2025: 1}


# 10
def test_cloud_cover_share_bands() -> None:
    values = [0.0, 24.9, 25.0, 49.9, 50.0, 74.9, 75.0, 100.0, 100.0, 100.0]
    table = _hours("berlin", "2025-01-10T00:00", len(values), cloud_cover=values)

    share = climate.cloud_cover_share(table)

    assert _as_dict(share, "band", "share") == pytest.approx(
        {"0-25": 0.2, "25-50": 0.2, "50-75": 0.2, "75-100": 0.4}
    )
    assert list(share["band"]) == list(climate.CLOUD_COVER_BANDS)


# 11
@pytest.mark.parametrize("bad", [-0.1, 100.1, math.nan])
def test_cloud_cover_share_rejects_out_of_range(bad: float) -> None:
    table = _hours("berlin", "2025-01-10T00:00", 2, cloud_cover=[50.0, bad])

    with pytest.raises(ValueError):
        climate.cloud_cover_share(table)


def _layer_rows(city: str, start: str, rows: list[tuple[str | None, str | None, float | None]]):
    """（電文, 1 層目の量, 1 層目の高さ）の並び。2〜4 層目は空。"""
    table = _hours(
        city,
        start,
        len(rows),
        metar=[metar for metar, _, _ in rows],
        sky_cover_1=[cover for _, cover, _ in rows],
        sky_height_1_m=[height for _, _, height in rows],
    )
    for number in (2, 3, 4):
        table[f"sky_cover_{number}"] = None
        table[f"sky_height_{number}_m"] = None
    for name in table.columns:
        if name.startswith("sky_cover_") or name == "metar":
            table[name] = table[name].astype("str").where(table[name].notna())
        if name.startswith("sky_height_"):
            table[name] = table[name].astype("float64")
    return table


# 12
def test_low_ceiling_share_excludes_unknown() -> None:
    table = _layer_rows(
        "berlin",
        "2025-01-10T00:00",
        [
            ("EDDB 100000Z BKN010", "BKN", 300.0),
            ("EDDB 100100Z CAVOK", None, None),
            ("EDDB 100200Z BKN///", "BKN", None),  # 高さがない：分母に入らない
            (None, None, None),  # METAR がない：分母に入らない
        ],
    )

    share = climate.monthly_low_ceiling_share(table)

    assert _as_dict(share, "month", "share") == {1: 0.5}


# 13
def test_low_ceiling_share_cap_is_not_low() -> None:
    table = _layer_rows(
        "berlin",
        "2025-01-10T00:00",
        [
            ("EDDB 100000Z OVC050", "OVC", 1524.0),
            ("EDDB 100100Z OVC049", "OVC", 1523.9),
        ],
    )

    share = climate.monthly_low_ceiling_share(table)

    assert _as_dict(share, "month", "share") == {1: 0.5}


# 14
def test_metar_auto_share() -> None:
    table = _hours(
        "berlin",
        "2025-01-10T00:00",
        4,
        metar=[
            "EDDB 100020Z AUTO 21016KT CAVOK",
            "EDDB 100120Z 21016KT CAVOK",
            "EDDB 100220Z AUTOMATIC 21016KT",
            None,
        ],
    )

    share = climate.yearly_metar_auto_share(table)

    assert _as_dict(share, "year", "share") == pytest.approx({2025: 1 / 3})


# 15
@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        ("-RA", True),
        ("+SHRA", True),
        ("-SHSNRAGS", True),
        ("TSRA", True),
        ("-FZDZ", True),
        ("-SG", True),
        ("+TSGRRA", True),
        ("-PL", True),
        ("UP", True),
        ("BR -RA", True),
        ("RA", True),
        ("SN", True),
        ("VCSH", False),
        ("VCTS", False),
        # 規格では VC と降水の記号を組み合わせないが、飛行場の上でない現象は数えない決まりを守る。
        ("VCRA", False),
        ("TS", False),
        ("BR", False),
        ("FZFG", False),
        ("BCFG", False),
        ("BLSN", False),
        ("DRSN", False),
        ("DRDU", False),
        ("//", False),
        # 2 文字ずつに分けられない壊れた群は数えない。
        ("-R", False),
        ("RAS", False),
        ("", False),
        (None, False),
    ],
)
def test_is_precipitation(codes: str | None, expected: bool) -> None:
    assert climate.is_precipitation(codes) is expected


# 追加 2 の⑥：星空日和の夜。暗い時間（太陽が −18° より下）は USNO の天文薄明の表で決める。
_CLOUDY = 90.0
_CLEAR = 10.0


def _night_table(
    city: str, day: date, clear_dark: int, clear_value: float = _CLEAR
) -> tuple[pd.DataFrame, int]:
    """`day` の 0 時（UTC）から 48 時間。

    `day` の夜の暗い正時のうち、先頭の `clear_dark` 個を晴れにする。

    昼（暗くない時間）は晴れ、ほかの夜の暗い時間は曇り。戻り値は表と、`day` の夜の暗い正時の数。
    """
    twilight = usno_twilight(city, "astronomical")
    dusk, dawn = twilight[day][1], twilight[day + timedelta(days=1)][0]
    assert dusk is not None and dawn is not None
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    times = [start + timedelta(hours=hour) for hour in range(48)]
    # USNO は分単位で、こちらの計算とは ±2 分ずれうる。境目の近くの正時は使わない。
    margin = timedelta(minutes=2)
    assert all(abs(at - dusk) > margin and abs(at - dawn) > margin for at in times)
    night = [dusk < at < dawn for at in times]
    others = [usno_twilight(city, "astronomical")[at.date()] for at in times]
    dark_anywhere = [
        (end is not None and at > end) or (begin is not None and at < begin)
        for at, (begin, end) in zip(times, others, strict=True)
    ]
    cloud: list[float] = []
    clear_left = clear_dark
    for in_night, dark in zip(night, dark_anywhere, strict=True):
        if in_night:
            cloud.append(clear_value if clear_left > 0 else _CLOUDY)
            clear_left -= 1
        else:
            cloud.append(_CLOUDY if dark else _CLEAR)
    return _hours(city, start.isoformat(), 48, cloud_cover=cloud), sum(night)


# 「ちょうど半分」を作れるように、暗い正時が偶数の夜を使う。
_EVEN_NIGHT = date(2026, 4, 15)


def test_star_nights_half_clear_is_star() -> None:
    _, dark = _night_table("tokyo", _EVEN_NIGHT, 0)
    assert dark % 2 == 0
    table, _ = _night_table("tokyo", _EVEN_NIGHT, dark // 2)

    result = climate.monthly_star_nights(table)

    assert _as_dict(result, "month", "days") == {4: 1.0}


def test_star_nights_less_than_half_clear_is_not_star() -> None:
    _, dark = _night_table("tokyo", _EVEN_NIGHT, 0)
    assert dark % 2 == 0
    table, _ = _night_table("tokyo", _EVEN_NIGHT, dark // 2 - 1)

    result = climate.monthly_star_nights(table)

    assert _as_dict(result, "month", "days") == {4: 0.0}


def test_star_nights_daytime_clear_does_not_count() -> None:
    # 昼はすべて晴れ、夜の暗い時間はすべて曇り。
    table, _ = _night_table("tokyo", date(2026, 1, 15), 0)

    result = climate.monthly_star_nights(table)

    assert _as_dict(result, "month", "days") == {1: 0.0}


def test_star_nights_cloud_cover_boundary() -> None:
    # 25 % 未満が晴れ。25.0 は晴れではない。
    clear, _ = _night_table("tokyo", date(2026, 1, 15), 48, clear_value=24.9)
    edge, _ = _night_table("tokyo", date(2026, 1, 15), 48, clear_value=25.0)

    assert _as_dict(climate.monthly_star_nights(clear), "month", "days") == {1: 1.0}
    assert _as_dict(climate.monthly_star_nights(edge), "month", "days") == {1: 0.0}


def test_star_nights_without_darkness_are_not_star() -> None:
    # ベルリンの夏至の前後は、太陽が −18° まで沈まない（USNO の表で「////」）。
    # 空がずっと晴れでも数えない。
    twilight = usno_twilight("berlin", "astronomical")
    days = [date(2026, 6, 20) + timedelta(days=n) for n in range(4)]
    assert all(twilight[day] == (None, None) for day in days)
    table = _hours("berlin", "2026-06-21T00:00", 48, cloud_cover=[_CLEAR] * 48)

    result = climate.monthly_star_nights(table)

    assert _as_dict(result, "month", "days") == {6: 0.0}


def test_precipitation_observed_days_average_per_year() -> None:
    def day(local_day: str, codes: list[str | None]) -> pd.DataFrame:
        table = _tokyo_day(local_day)
        table["weather_codes"] = codes
        return table

    dry: list[str | None] = [None] * 24
    rain: list[str | None] = ["-RA", *[None] * 23]
    vicinity: list[str | None] = ["VCSH", *[None] * 23]
    table = _concat(
        day("2024-03-01", rain),
        day("2024-03-02", rain),
        day("2025-03-01", vicinity),
        day("2025-03-02", rain),
        day("2025-03-03", dry),
    )

    observed = climate.monthly_precipitation_observed_days(table)

    assert _as_dict(observed, "month", "days") == {3: 1.5}


# 追加：1 年あたりの合計
def test_yearly_wet_days_sums_monthly_averages() -> None:
    # 1 月は 2 年ぶん（2 日と 1 日 → 年あたり 1.5 日）、2 月は 1 年ぶん（1 日）。合計は 2.5 日。
    table = _concat(
        _wet_day("2024-01-10", 1.0),
        _wet_day("2024-01-11", 2.0),
        _wet_day("2025-01-10", 1.5),
        _wet_day("2025-01-11", 0.0),
        _wet_day("2025-02-10", 3.0),
    )

    total = climate.yearly_wet_days(table)

    assert _as_dict(total, "city", "days") == {"tokyo": 2.5}


def test_yearly_wet_days_uses_threshold_boundary() -> None:
    table = _concat(_wet_day("2025-01-10", 0.99), _wet_day("2025-02-10", 1.0))

    total = climate.yearly_wet_days(table)

    assert _as_dict(total, "city", "days") == {"tokyo": 1.0}


def _summary_hours(city: str, start: str, count: int) -> pd.DataFrame:
    table = _layer_rows(city, start, [("XXXX 000000Z CAVOK", None, None)] * count)
    table["metar_temperature_c"] = 10.0
    table["metar_dew_point_c"] = 4.0
    table["temperature_c"] = 11.0
    table["wind_speed_ms"] = 3.0
    table["precipitation_mm"] = 0.0
    table["cloud_cover"] = 50.0
    table["weather_codes"] = None
    return table


def _summary_table() -> pd.DataFrame:
    tokyo = _summary_hours("tokyo", "2025-01-09T15:00", 48)
    berlin = _summary_hours("berlin", "2025-01-09T23:00", 48)
    return _concat(tokyo, berlin)


# 16
def test_climate_summary_keys() -> None:
    summary = climate.climate_summary(_summary_table(), years=[2025], mode="sample")

    assert set(summary) == {"mode", "source", "period", "cities"}
    assert summary["mode"] == "sample"
    assert summary["period"] == {"start": "2025-01-01", "end": "2025-12-31", "dates": "local"}
    assert set(summary["cities"]) == {"tokyo", "berlin"}
    for city in summary["cities"].values():
        assert set(city) == {"monthly", "yearly", "cloud_cover_share", "wet_days_1mm_per_year"}
        assert city["wet_days_1mm_per_year"] == 0.0
        assert [row["month"] for row in city["monthly"]] == list(range(1, 13))
        assert set(city["monthly"][0]) == {
            "month",
            "temperature_c_metar",
            "temperature_c_reanalysis",
            "dew_point_c_metar",
            "wind_speed_ms_reanalysis",
            "star_nights",
            "wet_days_1mm",
            "precipitation_observed_days",
            "low_ceiling_share",
        }
        assert city["monthly"][0]["temperature_c_metar"] == 10.0
        assert city["monthly"][0]["dew_point_c_metar"] == 4.0
        assert city["monthly"][0]["wind_speed_ms_reanalysis"] == 3.0
        # 雲量 50 % の表なので、星空日和の夜はない（データのある 1 月は 0、ない月は null）。
        assert city["monthly"][0]["star_nights"] == 0.0
        assert city["monthly"][5]["star_nights"] is None
        assert city["monthly"][0]["low_ceiling_share"] == 0.0
        # データのない月は null。
        assert city["monthly"][5]["temperature_c_metar"] is None
        assert [row["year"] for row in city["yearly"]] == [2025]
        assert set(city["yearly"][0]) == {
            "year",
            "precipitation_mm",
            "complete_days",
            "metar_auto_share",
        }
        assert city["yearly"][0]["complete_days"] == 2
        assert city["cloud_cover_share"] == {"0-25": 0.0, "25-50": 0.0, "50-75": 1.0, "75-100": 0.0}


def test_climate_summary_keeps_only_given_years() -> None:
    # 期間の外（東京の 2024-01-01）の行は、気温を変えておく。混ざれば 1 月の平均が変わる。
    outside = _summary_hours("tokyo", "2023-12-31T15:00", 24)
    outside["metar_temperature_c"] = 30.0
    table = _concat(_summary_table(), outside)

    summary = climate.climate_summary(table, years=[2025], mode="sample")

    assert [row["year"] for row in summary["cities"]["tokyo"]["yearly"]] == [2025]
    assert summary["cities"]["tokyo"]["yearly"][0]["complete_days"] == 2
    assert summary["cities"]["tokyo"]["monthly"][0]["temperature_c_metar"] == 10.0


def test_climate_summary_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        climate.climate_summary(_summary_table(), years=[2025], mode="partial")


def test_climate_summary_rejects_empty_years() -> None:
    with pytest.raises(ValueError):
        climate.climate_summary(_summary_table(), years=[], mode="sample")


# 17
def test_climate_summary_has_no_nan() -> None:
    summary = climate.climate_summary(_summary_table(), years=[2025], mode="sample")

    json.dumps(summary, allow_nan=False)


def test_climate_summary_rounds_values() -> None:
    table = _summary_table()
    table["metar_temperature_c"] = 10.04
    table.loc[table.index[0], "cloud_cover"] = 10.0

    summary = climate.climate_summary(table, years=[2025], mode="sample")

    assert summary["cities"]["tokyo"]["monthly"][0]["temperature_c_metar"] == 10.0
    share = summary["cities"]["tokyo"]["cloud_cover_share"]
    assert share["0-25"] == round(1 / 48, 3)


def test_climate_summary_has_wet_days_per_year() -> None:
    # 東京の 2025-01-10 だけ 1 mm 以上（1.04 mm）。1 月が 1 日で、合計は 1.0 日。
    table = _summary_table()
    table.loc[table.index[0], "precipitation_mm"] = 1.04

    summary = climate.climate_summary(table, years=[2025], mode="sample")

    assert summary["cities"]["tokyo"]["wet_days_1mm_per_year"] == 1.0
    assert summary["cities"]["berlin"]["wet_days_1mm_per_year"] == 0.0
