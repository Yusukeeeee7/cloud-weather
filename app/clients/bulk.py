"""期間をまとめて取得する外部API（学習データ用）に共通の、タイムアウトとリトライ。"""

import asyncio
import logging
from collections.abc import Mapping, Sequence

import httpx

from app.cities import City
from app.clients import open_meteo
from app.config import Settings
from app.errors import UpstreamError

logger = logging.getLogger(__name__)

# Open-Meteo の過去データは 1940 年から。上限は /daylight の日付の範囲に合わせる。
MIN_YEAR = 1940
MAX_YEAR = 2100

Params = Mapping[str, str | float | Sequence[str]]


class _RetryableError(UpstreamError):
    """やり直せば直るかもしれない失敗（通信の失敗、5xx）。"""


def build_bulk_http_client(base_url: str, settings: Settings) -> httpx.AsyncClient:
    timeout = httpx.Timeout(
        settings.data_fetch_timeout_s, connect=settings.open_meteo_connect_timeout_s
    )
    return httpx.AsyncClient(base_url=base_url, timeout=timeout, follow_redirects=False)


def validated(city: City, year: int) -> tuple[City, int]:
    """都市は許可リスト、年は範囲の中だけ。外れていれば ValueError（通信しない）。"""
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise ValueError(f"year must be between {MIN_YEAR} and {MAX_YEAR}")
    return City(city), year


async def get_text(http: httpx.AsyncClient, path: str, params: Params, settings: Settings) -> str:
    """GET して本文を返す。失敗は UpstreamError（リトライの決まりは Open-Meteo と同じ）。"""
    retries = settings.open_meteo_max_retries
    for retry in range(retries):
        try:
            return await _get_once(http, path, params, settings.data_fetch_timeout_s)
        except _RetryableError:
            logger.warning("bulk download retry %d of %d", retry + 1, retries)
            await open_meteo.wait(settings.open_meteo_retry_backoff_s * 2**retry)
    return await _get_once(http, path, params, settings.data_fetch_timeout_s)


async def _get_once(
    http: httpx.AsyncClient, path: str, params: Params, total_timeout_s: float
) -> str:
    try:
        async with asyncio.timeout(total_timeout_s):
            response = await http.get(path, params=dict(params))
    except (httpx.TransportError, TimeoutError) as exc:
        logger.warning("bulk download failed: %s", type(exc).__name__)
        raise _RetryableError("request failed") from exc
    except httpx.HTTPError as exc:
        logger.warning("bulk download failed: %s", type(exc).__name__)
        raise UpstreamError("request failed") from exc
    if response.status_code != httpx.codes.OK:
        logger.warning("bulk download returned status %d", response.status_code)
        # 4xx（429・422 を含む）は繰り返さない。
        if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise _RetryableError("server error")
        raise UpstreamError("unexpected status")
    if not response.text.strip():
        logger.warning("bulk download returned an empty body")
        raise UpstreamError("empty body")
    return response.text
