from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.cities import City
from app.clients.open_meteo import OpenMeteoClient
from app.schemas import ErrorResponse, WeatherResponse
from app.services import weather as weather_service
from app.services.weather import Clock, utc_now

router = APIRouter()


def get_clock() -> Clock:
    return utc_now


def get_open_meteo_client(request: Request) -> OpenMeteoClient:
    client = request.app.state.open_meteo
    assert isinstance(client, OpenMeteoClient)
    return client


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
    city: City = City.TOKYO,
) -> WeatherResponse:
    return await weather_service.get_weather(city, client, clock)
