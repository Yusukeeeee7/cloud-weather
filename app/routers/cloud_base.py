from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.cache import Cache
from app.cities import City
from app.clients.open_meteo import OpenMeteoClient
from app.config import Settings, get_settings
from app.errors import ModelUnavailableError
from app.routers.weather import get_cache, get_clock, get_open_meteo_client
from app.schemas import CloudBaseForecastResponse, CloudBaseResponse, ErrorResponse
from app.services import cloud_base as cloud_base_service
from app.services import cloud_base_forecast as cloud_base_forecast_service
from app.services.weather import Clock
from ml.model import CloudBaseModel

router = APIRouter()


def get_cloud_base_model(request: Request) -> CloudBaseModel | None:
    # 起動のときに読み込んだもの。読めなかった場合は None。
    model: CloudBaseModel | None = request.app.state.cloud_base_model
    return model


@router.get(
    "/cloud-base",
    responses={
        422: {"model": ErrorResponse, "description": "invalid_city"},
        502: {"model": ErrorResponse, "description": "upstream_error"},
        503: {"model": ErrorResponse, "description": "model_unavailable"},
    },
)
async def get_cloud_base(
    client: Annotated[OpenMeteoClient, Depends(get_open_meteo_client)],
    clock: Annotated[Clock, Depends(get_clock)],
    cache: Annotated[Cache, Depends(get_cache)],
    settings: Annotated[Settings, Depends(get_settings)],
    model: Annotated[CloudBaseModel | None, Depends(get_cloud_base_model)],
    city: City = City.TOKYO,
) -> CloudBaseResponse:
    # city の検証（422）の後、外部APIを呼ぶ前に判定する。
    if model is None:
        raise ModelUnavailableError("model is not loaded")
    return await cloud_base_service.get_cloud_base(
        city, client, clock, cache, settings.cache_ttl_s, settings.cache_stale_max_age_s, model
    )


@router.get(
    "/cloud-base/forecast",
    responses={
        422: {"model": ErrorResponse, "description": "invalid_city"},
        502: {"model": ErrorResponse, "description": "upstream_error"},
        503: {"model": ErrorResponse, "description": "model_unavailable"},
    },
)
async def get_cloud_base_forecast(
    client: Annotated[OpenMeteoClient, Depends(get_open_meteo_client)],
    clock: Annotated[Clock, Depends(get_clock)],
    cache: Annotated[Cache, Depends(get_cache)],
    settings: Annotated[Settings, Depends(get_settings)],
    model: Annotated[CloudBaseModel | None, Depends(get_cloud_base_model)],
    city: City = City.TOKYO,
) -> CloudBaseForecastResponse:
    # /cloud-base と同じく、city の検証（422）の後、外部APIを呼ぶ前に判定する。
    if model is None:
        raise ModelUnavailableError("model is not loaded")
    return await cloud_base_forecast_service.get_cloud_base_forecast(
        city, client, clock, cache, settings.cache_ttl_s, settings.cache_stale_max_age_s, model
    )
