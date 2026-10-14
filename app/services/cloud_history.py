"""過去 24 時間の雲量（`/cloud-history`）。`/weather` と同じ保存値の hourly から選ぶ。"""

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.cache import Cache
from app.cities import City
from app.clients.open_meteo import OpenMeteoClient
from app.errors import UpstreamError
from app.schemas import CloudCover, CloudHistoryHour, CloudHistoryResponse
from app.services.forecast import INVALID_RESPONSE_ERRORS, MAX_HOURLY_ROWS, from_unix, latest_hour
from app.services.weather import Clock, Source, get_forecast

logger = logging.getLogger(__name__)

HISTORY_COUNT = 24
_HOUR_S = 3600


class _RawHistory(BaseModel):
    """Open-Meteo の hourly（列ごとの配列）のうち、使う項目。時刻は UNIX 秒。"""

    # 数値の文字列や真偽値、小数を雲量として受け付けない。
    model_config = ConfigDict(strict=True)

    time: list[int]
    cloud_cover: list[int]
    cloud_cover_low: list[int]
    cloud_cover_mid: list[int]
    cloud_cover_high: list[int]


def _columns(raw: Mapping[str, Any]) -> dict[str, list[Any]]:
    section = raw.get("hourly")
    if not isinstance(section, Mapping):
        raise ValueError("hourly is not an object")
    columns: dict[str, list[Any]] = {}
    for name in _RawHistory.model_fields:
        column = section.get(name)
        if not isinstance(column, list):
            raise ValueError("hourly column is missing or not an array")
        columns[name] = column
    rows = len(columns["time"])
    # 長さが違う列は、どの行がどの時刻か分からない。
    if rows > MAX_HOURLY_ROWS or any(len(column) != rows for column in columns.values()):
        raise ValueError("unexpected hourly column length")
    return columns


def _parse_window(raw: Mapping[str, Any], now: datetime) -> _RawHistory:
    columns = _columns(raw)
    times = columns["time"]
    first = latest_hour(now) - timedelta(hours=HISTORY_COUNT - 1)
    # その時刻の行がなければ ValueError（過去の時間のない保存値など）。
    # 整数でない時刻は、ここで見つからないか、下の strict の検証で落ちる。
    start = times.index(int(first.timestamp()))
    if len(times) - start < HISTORY_COUNT:
        raise ValueError("not enough hourly rows")
    # 返す範囲だけを検証する（範囲の外の null は見ない）。
    window = _RawHistory.model_validate(
        {name: column[start : start + HISTORY_COUNT] for name, column in columns.items()}
    )
    steps = {later - earlier for earlier, later in zip(window.time, window.time[1:], strict=False)}
    if steps != {_HOUR_S}:
        raise ValueError("hourly times are not consecutive")
    return window


def build_cloud_history_response(
    city: City, raw: Mapping[str, Any], now: datetime
) -> CloudHistoryResponse:
    """hourly から、`now` 以前の最も近い正時までの 24 件を古い順に選ぶ。

    使えなければ UpstreamError。
    """
    try:
        window = _parse_window(raw, now)
    except INVALID_RESPONSE_ERRORS as exc:
        logger.warning("open-meteo response has no usable hourly rows for cloud history")
        raise UpstreamError("invalid hourly history") from exc
    return CloudHistoryResponse(
        city=city.value,
        hourly=[
            CloudHistoryHour(
                time=from_unix(window.time[row]),
                cloud_cover=CloudCover(
                    total=window.cloud_cover[row],
                    low=window.cloud_cover_low[row],
                    mid=window.cloud_cover_mid[row],
                    high=window.cloud_cover_high[row],
                ),
            )
            for row in range(HISTORY_COUNT)
        ],
    )


async def get_cloud_history(
    city: City,
    client: OpenMeteoClient,
    clock: Clock,
    cache: Cache,
    ttl_s: int,
    stale_max_age_s: int,
) -> CloudHistoryResponse:
    """`/weather` と同じ保存値・同じ決まり（TTL・stale）で予報を取り、その時刻で選ぶ。"""

    def build(raw: Mapping[str, Any], source: Source) -> CloudHistoryResponse:
        return build_cloud_history_response(city, raw, source.now)

    return await get_forecast(city, client, clock, cache, ttl_s, stale_max_age_s, build)
