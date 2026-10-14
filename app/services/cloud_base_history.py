"""過去 24 時間の雲底（`/cloud-base/history`）。予測の作り方は `/cloud-base` と同じ。"""

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.cache import Cache
from app.cities import City
from app.clients.open_meteo import OpenMeteoClient
from app.errors import UpstreamError
from app.schemas import CloudBaseForecastHour, CloudBaseHistoryResponse
from app.services.cloud_base import input_rows, predict_rows
from app.services.cloud_history import history_times
from app.services.forecast import INVALID_RESPONSE_ERRORS
from app.services.weather import Clock, Source, get_forecast
from ml.model import CloudBaseModel

logger = logging.getLogger(__name__)


def build_cloud_base_history_response(
    city: City, raw: Mapping[str, Any], now: datetime, model: CloudBaseModel
) -> CloudBaseHistoryResponse:
    """`/cloud-history` と同じ 24 時刻（古い順）で予測する。使えなければ UpstreamError。"""
    times = history_times(now)
    try:
        # 過去の行がない・1 時間おきでない時刻は、その時刻の行が見つからずに失敗する。
        table = input_rows(city, raw, times)
    except INVALID_RESPONSE_ERRORS as exc:
        logger.warning("open-meteo response has no usable hourly rows for cloud base history")
        raise UpstreamError("invalid hourly rows") from exc
    predicted, baseline = predict_rows(model, table)
    return CloudBaseHistoryResponse(
        city=city.value,
        model_version=model.model_version,
        hourly=[
            CloudBaseForecastHour(time=at, predicted_m=p, baseline_m=b)
            for at, p, b in zip(times, predicted, baseline, strict=True)
        ],
    )


async def get_cloud_base_history(
    city: City,
    client: OpenMeteoClient,
    clock: Clock,
    cache: Cache,
    ttl_s: int,
    stale_max_age_s: int,
    model: CloudBaseModel,
) -> CloudBaseHistoryResponse:
    """`/weather` と同じ保存値・同じ決まり（TTL・stale）で予報を取り、その時刻で予測する。"""

    def build(raw: Mapping[str, Any], source: Source) -> CloudBaseHistoryResponse:
        return build_cloud_base_history_response(city, raw, source.now, model)

    return await get_forecast(city, client, clock, cache, ttl_s, stale_max_age_s, build)
