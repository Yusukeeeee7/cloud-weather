from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.cache import build_cache
from app.clients.open_meteo import OpenMeteoClient, build_http_client
from app.config import get_settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging
from app.routers import cloud_base, daylight, health, weather
from app.services.cloud_base import load_model


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.cloud_base_model = load_model()
    cache = build_cache(settings)
    app.state.weather_cache = cache
    try:
        async with build_http_client(settings) as http:
            app.state.open_meteo = OpenMeteoClient(http, settings)
            yield
    finally:
        await cache.close()


app = FastAPI(title="cloud-weather", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(health.router)
app.include_router(daylight.router)
app.include_router(weather.router)
app.include_router(cloud_base.router)
