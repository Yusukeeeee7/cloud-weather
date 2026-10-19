"""#25 気候の比較ページの集計。

`observations.parquet`（都市 × 正時、UTC）から月ごと・年ごとの値を作る。
日ごとの集計は、現地の日付で区切り、その日の行がそろった日だけを使う
（夏時間の切り替え日は 23・25 行）。
値は METAR（実測）を優先し、METAR にないもの（降水量・空全体の雲量）だけ Open-Meteo の再解析を使う。
"""

import math
import numbers
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any, Literal

import pandas as pd

from app.cities import CITIES, City
from app.services.solar import solar_elevation_deg
from ml.target import CEILING_CAP_M, target_m

SOURCE = "data/processed/observations.parquet"
MODES = ("full", "sample")
WET_DAY_MM = 1.0
# 雲量（%）の区分。下の端を含み、上の端を含まない（最後の区分だけ 100 を含む）。
CLOUD_COVER_BANDS = ("0-25", "25-50", "50-75", "75-100")
_BAND_LOWER_EDGES = (25.0, 50.0, 75.0)
# WMO-No. 782（2025 年版）5 節の Code table 4678 の降水（spec 7「METAR の天気の記号」）。
PRECIPITATION_CODES = frozenset({"DZ", "RA", "SN", "SG", "PL", "GR", "GS", "UP"})
# 風で吹き上げられた雪・砂・塵（降水ではない）と、飛行場から 8〜16 km の現象。
_RAISED = frozenset({"DR", "BL"})
_VICINITY = "VC"
_AUTO = r"\bAUTO\b"
_TEMPERATURE_COLUMNS = {"metar": "metar_temperature_c", "reanalysis": "temperature_c"}
_MONTHS = range(1, 13)
# 星空日和の夜：天文薄明（spec 5 の `/daylight`）の高度より下を暗い時間とし、
# 雲量 25 % 未満を晴れとする。
ASTRONOMICAL_DARK_DEG = -18.0
STAR_CLEAR_COVER = 25.0

TemperatureSource = Literal["metar", "reanalysis"]


def _local_times(observations: pd.DataFrame) -> pd.Series:
    """`time`（UTC）を `city` のタイムゾーンの時刻（タイムゾーンなし）にする。"""
    time = observations["time"]
    dtype = time.dtype
    if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
        raise ValueError("time must be timezone-aware UTC")
    local = pd.Series(pd.NaT, index=observations.index, dtype="datetime64[ns]")
    for name in observations["city"].unique():
        rows = observations["city"] == name
        timezone = CITIES[City(name)].timezone
        local[rows] = time[rows].dt.tz_convert(timezone).dt.tz_localize(None)
    return local


def local_date(observations: pd.DataFrame) -> pd.Series:
    """`time`（UTC）を、`city` のタイムゾーンでの日付にする。"""
    dates: pd.Series = _local_times(observations).dt.date
    return dates.rename("local_date")


def _hours_in_day(city: str, day: date) -> int:
    """その現地の日の長さ（時間）。夏時間の切り替え日は 23・25。"""
    timezone = CITIES[City(city)].timezone
    start = pd.Timestamp(day).tz_localize(timezone)
    end = pd.Timestamp(day + timedelta(days=1)).tz_localize(timezone)
    return int((end - start) / pd.Timedelta(hours=1))


def complete_days(observations: pd.DataFrame) -> pd.DataFrame:
    """現地の日の行がそろった日の行だけを残し、`local_date` の列を足す。"""
    table = observations.assign(local_date=local_date(observations))
    counts = table.groupby(["city", "local_date"])["time"].transform("nunique")
    lengths = {
        (city, day): _hours_in_day(city, day)
        for city, day in table[["city", "local_date"]].drop_duplicates().itertuples(index=False)
    }
    expected = pd.Series(
        [lengths[key] for key in zip(table["city"], table["local_date"], strict=True)],
        index=table.index,
        dtype="int64",
    )
    return table[counts == expected]


def _average_days_per_year(days: pd.DataFrame, flag: pd.Series) -> pd.DataFrame:
    """日ごとの印（真偽）を、月ごとの「年あたりの日数」にする。分母はその月のある年の数。"""
    dates = pd.to_datetime(days["local_date"])
    table = pd.DataFrame(
        {
            "city": days["city"],
            "year": dates.dt.year,
            "month": dates.dt.month,
            "flag": flag.astype("bool"),
        }
    )
    grouped = table.groupby(["city", "month"])
    result = grouped["flag"].sum() / grouped["year"].nunique()
    return result.astype("float64").rename("days").reset_index()


def daily_precipitation_mm(observations: pd.DataFrame) -> pd.DataFrame:
    """現地の日ごとの降水量の合計（再解析）。そろった日で、値の欠けがない日だけ。"""
    days = complete_days(observations)
    values = days["precipitation_mm"].astype("float64")
    grouped = values.groupby([days["city"], days["local_date"]])
    result = pd.DataFrame({"precipitation_mm": grouped.sum(), "missing": grouped.count()})
    result["missing"] = grouped.size() - result["missing"]
    result = result[result["missing"] == 0]
    return result[["precipitation_mm"]].reset_index()


def monthly_wet_days(observations: pd.DataFrame, threshold_mm: float = WET_DAY_MM) -> pd.DataFrame:
    """月ごとの「`threshold_mm` 以上の日」の数の、年あたりの平均（再解析）。"""
    daily = daily_precipitation_mm(observations)
    return _average_days_per_year(daily, daily["precipitation_mm"] >= threshold_mm)


def yearly_wet_days(observations: pd.DataFrame, threshold_mm: float = WET_DAY_MM) -> pd.DataFrame:
    """1 年あたりの「`threshold_mm` 以上の日」の数。

    月ごとの年あたりの日数（丸める前）を 12 か月ぶん足したもの。
    """
    monthly = monthly_wet_days(observations, threshold_mm)
    return monthly.groupby("city")["days"].sum().rename("days").reset_index()


def yearly_precipitation_mm(observations: pd.DataFrame) -> pd.DataFrame:
    """年ごとの降水量の合計と、合計に使ったそろった日の数（再解析）。"""
    daily = daily_precipitation_mm(observations)
    daily["year"] = pd.to_datetime(daily["local_date"]).dt.year
    grouped = daily.groupby(["city", "year"])["precipitation_mm"]
    return pd.DataFrame(
        {"precipitation_mm": grouped.sum(), "complete_days": grouped.size()}
    ).reset_index()


def monthly_temperature_c(observations: pd.DataFrame, source: TemperatureSource) -> pd.DataFrame:
    """月ごとの平均気温。`source` は `metar`（実測）か `reanalysis`（再解析）。欠けた行は除く。"""
    if source not in _TEMPERATURE_COLUMNS:
        raise ValueError("source must be 'metar' or 'reanalysis'")
    return _monthly_mean(observations, _TEMPERATURE_COLUMNS[source], "temperature_c")


def monthly_dew_point_c(observations: pd.DataFrame) -> pd.DataFrame:
    """月ごとの平均の露点（METAR、実測）。欠けた行は除く。"""
    return _monthly_mean(observations, "metar_dew_point_c", "dew_point_c")


def monthly_wind_speed_ms(observations: pd.DataFrame) -> pd.DataFrame:
    """月ごとの平均風速（再解析、m/s）。欠けた行は除く。"""
    return _monthly_mean(observations, "wind_speed_ms", "wind_speed_ms")


def _monthly_mean(observations: pd.DataFrame, column: str, name: str) -> pd.DataFrame:
    values = observations[column].astype("float64")
    months = _local_times(observations).dt.month
    means = values.groupby([observations["city"], months.rename("month")]).mean().dropna()
    return means.rename(name).reset_index()


def cloud_cover_share(observations: pd.DataFrame) -> pd.DataFrame:
    """雲量（再解析、%）の区分ごとの割合。0〜100 の外や欠けがあれば ValueError。"""
    values = observations["cloud_cover"].astype("float64")
    if values.isna().any() or (values < 0).any() or (values > 100).any():
        raise ValueError("cloud_cover must be 0 to 100")
    index = sum((values >= edge).astype("int64") for edge in _BAND_LOWER_EDGES)
    bands = pd.Series(index, index=observations.index, dtype="int64").map(
        dict(enumerate(CLOUD_COVER_BANDS))
    )
    counts = (
        bands.groupby([observations["city"], bands.rename("band")])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=list(CLOUD_COVER_BANDS), fill_value=0)
    )
    shares = counts.div(counts.sum(axis=1), axis=0)
    return shares.reset_index().melt(id_vars="city", var_name="band", value_name="share")


def monthly_low_ceiling_share(observations: pd.DataFrame) -> pd.DataFrame:
    """月ごとの「シーリングが 1,524 m より下」の時間の割合（METAR）。目的変数が欠ける行は除く。"""
    ceiling = target_m(observations)
    known = ceiling.notna()
    low = (ceiling < CEILING_CAP_M)[known].astype("float64")
    months = _local_times(observations).dt.month[known].rename("month")
    shares = low.groupby([observations["city"][known], months]).mean()
    return shares.rename("share").reset_index()


def yearly_metar_auto_share(observations: pd.DataFrame) -> pd.DataFrame:
    """年ごとの「電文に `AUTO`（自動観測）がある時間」の割合。METAR のない行は除く。"""
    reports = observations["metar"]
    known = reports.notna()
    auto = reports[known].str.contains(_AUTO, regex=True).astype("float64")
    years = _local_times(observations).dt.year[known].rename("year")
    shares = auto.groupby([observations["city"][known], years]).mean()
    return shares.rename("share").reset_index()


def _is_precipitation_group(group: str) -> bool:
    body = group.lstrip("+-")
    if len(body) % 2:
        return False
    parts = {body[start : start + 2] for start in range(0, len(body), 2)}
    if body.startswith(_VICINITY) or parts & _RAISED:
        return False
    return bool(parts & PRECIPITATION_CODES)


def is_precipitation(codes: object) -> bool:
    """`weather_codes`（空白で区切った天気の群）に、飛行場での降水があるか。"""
    if not isinstance(codes, str):
        return False
    return any(_is_precipitation_group(group) for group in codes.split())


def monthly_precipitation_observed_days(observations: pd.DataFrame) -> pd.DataFrame:
    """月ごとの「METAR で降水を観測した日」の数の、年あたりの平均。

    正時の観測（前後 30 分以内の 1 つ）のどれかで降水があった日。
    """
    days = complete_days(observations)
    observed = days["weather_codes"].map(is_precipitation).astype("bool")
    daily = (
        observed.groupby([days["city"], days["local_date"]]).any().rename("observed").reset_index()
    )
    return _average_days_per_year(daily, daily["observed"])


def _solar_elevation_deg(observations: pd.DataFrame) -> pd.Series:
    """その都市・その時刻の太陽の高度（`/daylight` と同じ計算）。"""
    values = [
        solar_elevation_deg(CITIES[City(name)].latitude, CITIES[City(name)].longitude, at)
        for name, at in zip(observations["city"], observations["time"], strict=True)
    ]
    return pd.Series(values, index=observations.index, dtype="float64")


def monthly_star_nights(observations: pd.DataFrame) -> pd.DataFrame:
    """月ごとの星空日和の夜の数の、年あたりの平均（このサイト独自の目安）。

    暗い正時（太陽が −18° より下）のうち、雲量（再解析）が 25 % 未満の時間が半分以上ある夜。
    夜は夕方の現地の日付で数える（正午から次の日の正午まで）。暗くならない夜は数えない。
    """
    dark = _solar_elevation_deg(observations) < ASTRONOMICAL_DARK_DEG
    clear = observations["cloud_cover"].astype("float64") < STAR_CLEAR_COVER
    nights = (_local_times(observations) - pd.Timedelta(hours=12)).dt.date
    table = pd.DataFrame(
        {"city": observations["city"], "local_date": nights, "dark": dark, "clear": dark & clear}
    )
    counts = table.groupby(["city", "local_date"])[["dark", "clear"]].sum().reset_index()
    star = (counts["dark"] > 0) & (counts["clear"] * 2 >= counts["dark"])
    return _average_days_per_year(counts, star)


def _rounded(value: object, digits: int) -> float | None:
    # numpy の数も numbers.Real に入る。NaN は None にする（JSON に NaN を書かない）。
    if not isinstance(value, numbers.Real) or math.isnan(value):
        return None
    return round(float(value), digits)


def _lookup(table: pd.DataFrame, city: str, key: str, value: str) -> dict[Any, Any]:
    rows = table[table["city"] == city]
    return dict(zip(rows[key], rows[value], strict=True))


def _city_summary(observations: pd.DataFrame, city: str, years: list[int]) -> dict[str, Any]:
    metar = _lookup(monthly_temperature_c(observations, "metar"), city, "month", "temperature_c")
    reanalysis = _lookup(
        monthly_temperature_c(observations, "reanalysis"), city, "month", "temperature_c"
    )
    dew = _lookup(monthly_dew_point_c(observations), city, "month", "dew_point_c")
    wind = _lookup(monthly_wind_speed_ms(observations), city, "month", "wind_speed_ms")
    wet = _lookup(monthly_wet_days(observations), city, "month", "days")
    observed = _lookup(monthly_precipitation_observed_days(observations), city, "month", "days")
    low = _lookup(monthly_low_ceiling_share(observations), city, "month", "share")
    star = _lookup(monthly_star_nights(observations), city, "month", "days")
    monthly = [
        {
            "month": month,
            "temperature_c_metar": _rounded(metar.get(month), 1),
            "temperature_c_reanalysis": _rounded(reanalysis.get(month), 1),
            "dew_point_c_metar": _rounded(dew.get(month), 1),
            "wind_speed_ms_reanalysis": _rounded(wind.get(month), 1),
            "wet_days_1mm": _rounded(wet.get(month), 1),
            "precipitation_observed_days": _rounded(observed.get(month), 1),
            "low_ceiling_share": _rounded(low.get(month), 3),
            "star_nights": _rounded(star.get(month), 1),
        }
        for month in _MONTHS
    ]

    precipitation = yearly_precipitation_mm(observations)
    totals = _lookup(precipitation, city, "year", "precipitation_mm")
    counts = _lookup(precipitation, city, "year", "complete_days")
    auto = _lookup(yearly_metar_auto_share(observations), city, "year", "share")
    yearly = [
        {
            "year": year,
            "precipitation_mm": _rounded(totals.get(year), 1),
            "complete_days": int(counts.get(year, 0)),
            "metar_auto_share": _rounded(auto.get(year), 3),
        }
        for year in years
    ]

    shares = _lookup(cloud_cover_share(observations), city, "band", "share")
    cloud = {band: _rounded(shares.get(band), 3) for band in CLOUD_COVER_BANDS}
    wet_total = _lookup(yearly_wet_days(observations), city, "city", "days")
    return {
        "monthly": monthly,
        "yearly": yearly,
        "cloud_cover_share": cloud,
        "wet_days_1mm_per_year": _rounded(wet_total.get(city), 1),
    }


def climate_summary(observations: pd.DataFrame, years: Iterable[int], mode: str) -> dict[str, Any]:
    """比較ページの JSON（`app/static/climate.json`）の中身。

    期間は `years` の現地の年。値のない所は None。
    """
    if mode not in MODES:
        raise ValueError("mode must be 'full' or 'sample'")
    chosen = sorted(set(years))
    if not chosen:
        raise ValueError("years must not be empty")
    in_period = _local_times(observations).dt.year.isin(chosen)
    table = observations[in_period]
    return {
        "mode": mode,
        "source": SOURCE,
        "period": {"start": f"{chosen[0]}-01-01", "end": f"{chosen[-1]}-12-31", "dates": "local"},
        "cities": {
            city.value: _city_summary(table[table["city"] == city.value], city.value, chosen)
            for city in City
        },
    }
