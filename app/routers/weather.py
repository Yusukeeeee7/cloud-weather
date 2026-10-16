from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.cache import Cache
from app.cities import City
from app.clients.open_meteo import OpenMeteoClient
from app.config import Settings, get_settings
from app.schemas import ErrorResponse, WeatherResponse
from app.services import weather as weather_service
from app.services.weather import Clock, utc_now

router = APIRouter()


def get_clock() -> Clock:
    return utc_now


def get_open_meteo_client(request: Request) -> OpenMeteoClient:
    client: OpenMeteoClient = request.app.state.open_meteo
    return client


def get_cache(request: Request) -> Cache:
    cache: Cache = request.app.state.weather_cache
    return cache


@router.get(
    "/weather",
    responses={
        422: {"model": ErrorResponse, "description": "invalid_city"},
        502: {"model": ErrorResponse, "description": "upstream_error"},
    },
)
async def get_weather(
    client: Annotated[OpenMeteoClient, Depends(get_open_meteo_client)],
    clock: Annotated[Clock, Depends(get_clock)],
    cache: Annotated[Cache, Depends(get_cache)],
    settings: Annotated[Settings, Depends(get_settings)],
    city: City = City.TOKYO,
) -> WeatherResponse:
    return await weather_service.get_weather(
        city, client, clock, cache, settings.cache_ttl_s, settings.cache_stale_max_age_s
    )
