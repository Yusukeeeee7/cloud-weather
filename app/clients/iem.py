"""Iowa Environmental Mesonet（IEM）の METAR の過去データ。"""

import logging

import httpx

from app.cities import CITIES, City
from app.clients import open_meteo
from app.clients.bulk import get_text, validated
from app.config import Settings
from app.errors import UpstreamError

logger = logging.getLogger(__name__)

ASOS_PATH = "/cgi-bin/request/asos.py"
# 気温・露点（華氏）、視程（マイル）、雲の層の量と高さ（フィート）、天気の記号、もとの電文。
COLUMNS = (
    "tmpf",
    "dwpf",
    "vsby",
    "skyc1",
    "skyc2",
    "skyc3",
    "skyc4",
    "skyl1",
    "skyl2",
    "skyl3",
    "skyl4",
    "wxcodes",
    "metar",
)
# 3 = 定時（Routine）、4 = 臨時（Specials）。
REPORT_TYPES = ("3", "4")
_HEADER_PREFIX = "station,valid"


class IemClient:
    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        self._http = http
        self._settings = settings
        self._requested = False

    async def fetch_metar(self, city: City, year: int) -> str:
        """その都市の空港の、1 年ぶん（UTC）の METAR を CSV の文字列で返す。"""
        city, year = validated(city, year)
        if self._requested:
            # 同じ IP からは 1 秒に 1 回まで（超えると 429）。
            await open_meteo.wait(self._settings.iem_request_interval_s)
        self._requested = True
        text = await get_text(self._http, ASOS_PATH, self._params(city, year), self._settings)
        if not text.startswith(_HEADER_PREFIX):
            logger.warning("iem returned a body that is not the expected CSV")
            raise UpstreamError("invalid body")
        return text

    @staticmethod
    def _params(city: City, year: int) -> dict[str, str | list[str]]:
        return {
            "station": CITIES[city].icao,
            "data": list(COLUMNS),
            # 開始を含み、終了を含まない。
            "sts": f"{year}-01-01T00:00:00Z",
            "ets": f"{year + 1}-01-01T00:00:00Z",
            "tz": "UTC",
            "format": "onlycomma",
            "missing": "empty",
            "trace": "empty",
            "report_type": list(REPORT_TYPES),
        }
