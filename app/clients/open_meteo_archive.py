"""Open-Meteo の過去データのAPI（1 時間ごとの気象）。"""

import json
import logging

import httpx

from app.cities import CITIES, City
from app.clients.bulk import get_text, validated
from app.config import Settings
from app.errors import UpstreamError

logger = logging.getLogger(__name__)

ARCHIVE_PATH = "/v1/archive"
# precipitation だけ「前の 1 時間の合計」、ほかは「その時刻の値」。
HOURLY_VARIABLES = (
    "temperature_2m",
    "dew_point_2m",
    "relative_humidity_2m",
    "pressure_msl",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "wind_speed_10m",
)


class OpenMeteoArchiveClient:
    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        self._http = http
        self._settings = settings

    async def fetch_hourly(self, city: City, year: int) -> str:
        """その都市の、1 年ぶん（UTC）の 1 時間ごとの気象を JSON の文字列で返す。"""
        city, year = validated(city, year)
        text = await get_text(self._http, ARCHIVE_PATH, self._params(city, year), self._settings)
        self._check(text)
        return text

    @staticmethod
    def _params(city: City, year: int) -> dict[str, str | float]:
        info = CITIES[city]
        return {
            "latitude": info.latitude,
            "longitude": info.longitude,
            "hourly": ",".join(HOURLY_VARIABLES),
            "start_date": f"{year}-01-01",
            "end_date": f"{year}-12-31",
            "wind_speed_unit": "ms",
            # timezone は指定しない（GMT）。時刻は UTC の UNIX 秒。
            "timeformat": "unixtime",
        }

    @staticmethod
    def _check(text: str) -> None:
        try:
            data = json.loads(text)
        except ValueError as exc:
            logger.warning("open-meteo archive returned a non-JSON body")
            raise UpstreamError("invalid body") from exc
        if not isinstance(data, dict) or data.get("error") or "hourly" not in data:
            logger.warning("open-meteo archive returned an unexpected body")
            raise UpstreamError("invalid body")
