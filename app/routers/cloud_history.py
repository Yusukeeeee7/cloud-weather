from typing import Annotated

from fastapi import APIRouter, Depends

from app.cache import Cache
from app.cities import City
from app.clients.open_meteo import OpenMeteoClient
from app.config import Settings, get_settings
from app.routers.weather import get_cache, get_clock, get_open_meteo_client
from app.schemas import CloudHistoryResponse, ErrorResponse
from app.services import cloud_history as cloud_history_service
from app.services.weather import Clock

router = APIRouter()


@router.get(
    "/cloud-history",
    responses={
        422: {"model": ErrorResponse, "description": "invalid_city"},
        502: {"model": ErrorResponse, "description": "upstream_error"},
    },
)
async def get_cloud_history(
    client: Annotated[OpenMeteoClient, Depends(get_open_meteo_client)],
    clock: Annotated[Clock, Depends(get_clock)],
    cache: Annotated[Cache, Depends(get_cache)],
    settings: Annotated[Settings, Depends(get_settings)],
    city: City = City.TOKYO,
) -> CloudHistoryResponse:
    return await cloud_history_service.get_cloud_history(
        city, client, clock, cache, settings.cache_ttl_s, settings.cache_stale_max_age_s
    )
