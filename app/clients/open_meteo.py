import asyncio
import logging
from typing import Any

import httpx

from app.cities import CITIES, City
from app.config import Settings
from app.errors import UpstreamError

logger = logging.getLogger(__name__)

FORECAST_PATH = "/v1/forecast"
CURRENT_VARIABLES = (
    "temperature_2m",
    "apparent_temperature",
    "dew_point_2m",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "wind_speed_10m",
)


def build_http_client(settings: Settings) -> httpx.AsyncClient:
    timeout = httpx.Timeout(
        settings.open_meteo_total_timeout_s, connect=settings.open_meteo_connect_timeout_s
    )
    return httpx.AsyncClient(
        base_url=settings.open_meteo_base_url, timeout=timeout, follow_redirects=False
    )


class OpenMeteoClient:
    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        self._http = http
        self._total_timeout_s = settings.open_meteo_total_timeout_s

    async def fetch_forecast(self, city: City) -> dict[str, Any]:
        response = await self._get(FORECAST_PATH, self._params(city))
        if response.status_code != httpx.codes.OK:
            logger.warning("open-meteo returned status %d", response.status_code)
            raise UpstreamError("unexpected status")
        return self._parse(response)

    @staticmethod
    def _params(city: City) -> dict[str, str | float]:
        info = CITIES[city]
        return {
            "latitude": info.latitude,
            "longitude": info.longitude,
            "current": ",".join(CURRENT_VARIABLES),
            "wind_speed_unit": "ms",
        }

    async def _get(self, path: str, params: dict[str, str | float]) -> httpx.Response:
        try:
            # httpx のタイムアウトは接続・読み取りなど段階ごとなので、全体の上限を別にかける。
            async with asyncio.timeout(self._total_timeout_s):
                return await self._http.get(path, params=params)
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("open-meteo request failed: %s", type(exc).__name__)
            raise UpstreamError("request failed") from exc

    @staticmethod
    def _parse(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("open-meteo returned a non-JSON body")
            raise UpstreamError("invalid body") from exc
        if not isinstance(data, dict):
            logger.warning("open-meteo returned an unexpected JSON type")
            raise UpstreamError("invalid body")
        return data
