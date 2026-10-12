import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.cache.base import CacheError

logger = logging.getLogger(__name__)


def build_redis_client(url: str, timeout_s: float) -> Redis:
    # 接続・読み書きの両方にタイムアウトをかける。値は文字列で受け取る。
    return Redis.from_url(
        url,
        socket_timeout=timeout_s,
        socket_connect_timeout=timeout_s,
        decode_responses=True,
    )


class RedisCache:
    def __init__(self, client: Redis) -> None:
        self._client = client

    async def get(self, key: str) -> str | None:
        try:
            value = await self._client.get(key)
        except RedisError as exc:
            # Redis の例外の文面（接続先を含みうる）は外に出さない。
            logger.warning("redis get failed: %s", type(exc).__name__)
            raise CacheError("redis get failed") from None
        if value is None or isinstance(value, str):
            return value
        raise CacheError("redis returned a non-text value")

    async def set(self, key: str, value: str, expire_s: int) -> None:
        try:
            await self._client.set(key, value, ex=expire_s)
        except RedisError as exc:
            logger.warning("redis set failed: %s", type(exc).__name__)
            raise CacheError("redis set failed") from None

    async def close(self) -> None:
        await self._client.aclose()
