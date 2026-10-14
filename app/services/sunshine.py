"""日差し（`/sunshine`）。`/weather` と同じ保存値の hourly から、同じ 24 時刻を選ぶ。"""

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.cache import Cache
from app.cities import City
from app.clients.open_meteo import OpenMeteoClient
from app.errors import UpstreamError
from app.schemas import SunshineHour, SunshineResponse
from app.services.forecast import (
    INVALID_RESPONSE_ERRORS,
    MAX_HOURLY_ROWS,
    forecast_times,
    from_unix,
)
from app.services.weather import Clock, Source, get_forecast

logger = logging.getLogger(__name__)


class _RawSunshine(BaseModel):
    """Open-Meteo の hourly（列ごとの配列）のうち、使う項目。時刻は UNIX 秒。値は前の 1 時間。"""

    # 数値の文字列や真偽値を数値として受け付けない。NaN・無限大も落とす。
    model_config = ConfigDict(strict=True, allow_inf_nan=False)

    time: list[int]
    sunshine_duration: list[float]
    direct_radiation: list[float]
    diffuse_radiation: list[float]


def _columns(raw: Mapping[str, Any]) -> dict[str, list[Any]]:
    section = raw.get("hourly")
    if not isinstance(section, Mapping):
        raise ValueError("hourly is not an object")
    columns: dict[str, list[Any]] = {}
    for name in _RawSunshine.model_fields:
        column = section.get(name)
        if not isinstance(column, list):
            raise ValueError("hourly column is missing or not an array")
        columns[name] = column
    rows = len(columns["time"])
    # 長さが違う列は、どの行がどの時刻か分からない。
    if rows > MAX_HOURLY_ROWS or any(len(column) != rows for column in columns.values()):
        raise ValueError("unexpected hourly column length")
    return columns


def _parse_window(raw: Mapping[str, Any], times: list[datetime]) -> _RawSunshine:
    columns = _columns(raw)
    # その時刻の行を順に探す。なければ ValueError（3 項目のない保存値・行が足りないなど）。
    # 整数でない時刻は、見つからないか、下の strict の検証で落ちる。
    rows = [columns["time"].index(int(at.timestamp())) for at in times]
    # 返す範囲だけを検証する（範囲の外の null は見ない）。
    return _RawSunshine.model_validate(
        {name: [column[row] for row in rows] for name, column in columns.items()}
    )


def build_sunshine_response(city: City, raw: Mapping[str, Any], now: datetime) -> SunshineResponse:
    """`/weather` の hourly と同じ 24 時刻の日照時間と日射。使えなければ UpstreamError。"""
    times = forecast_times(now)
    try:
        window = _parse_window(raw, times)
    except INVALID_RESPONSE_ERRORS as exc:
        logger.warning("open-meteo response has no usable hourly rows for sunshine")
        raise UpstreamError("invalid hourly sunshine") from exc
    return SunshineResponse(
        city=city.value,
        hourly=[
            SunshineHour(
                time=from_unix(window.time[row]),
                sunshine_s=window.sunshine_duration[row],
                direct_radiation_wm2=window.direct_radiation[row],
                diffuse_radiation_wm2=window.diffuse_radiation[row],
            )
            for row in range(len(times))
        ],
    )


async def get_sunshine(
    city: City,
    client: OpenMeteoClient,
    clock: Clock,
    cache: Cache,
    ttl_s: int,
    stale_max_age_s: int,
) -> SunshineResponse:
    """`/weather` と同じ保存値・同じ決まり（TTL・stale）で予報を取り、その時刻で選ぶ。"""

    def build(raw: Mapping[str, Any], source: Source) -> SunshineResponse:
        return build_sunshine_response(city, raw, source.now)

    return await get_forecast(city, client, clock, cache, ttl_s, stale_max_age_s, build)
