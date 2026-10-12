import asyncio
from typing import Any

import fakeredis
import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.cache import CacheError, RedisCache
from app.cache.redis import build_redis_client

KEY = "weather:tokyo"
EXPIRE_S = 900
# 実在しない接続先。クライアントを作るだけで、接続はしない。
DUMMY_URL = "redis://localhost:6379/0"


def _fake() -> fakeredis.FakeAsyncRedis:
    # 実物の Redis は使わない。redis パッケージのクライアントと同じ呼び出し方を通る。
    return fakeredis.FakeAsyncRedis(decode_responses=True)


def _disconnected() -> fakeredis.FakeAsyncRedis:
    server = fakeredis.FakeServer()
    server.connected = False
    return fakeredis.FakeAsyncRedis(server=server, decode_responses=True)


def test_redis_get_missing_returns_none() -> None:
    cache = RedisCache(_fake())

    assert asyncio.run(cache.get(KEY)) is None


def test_redis_set_then_get() -> None:
    async def scenario() -> tuple[str | None, str | None, str | None]:
        cache = RedisCache(_fake())
        await cache.set(KEY, "first", EXPIRE_S)
        await cache.set("weather:berlin", "other", EXPIRE_S)
        first = await cache.get(KEY)
        await cache.set(KEY, "second", EXPIRE_S)
        return first, await cache.get(KEY), await cache.get("weather:berlin")

    # バイト列ではなく文字列で返る。
    assert asyncio.run(scenario()) == ("first", "second", "other")


def test_redis_set_applies_expiry() -> None:
    async def scenario() -> int:
        client = _fake()
        await RedisCache(client).set(KEY, "value", EXPIRE_S)
        remaining: int = await client.ttl(KEY)
        return remaining

    # 期限なしのキーは -1 になる。期限付きで保存されていること。
    assert 0 < asyncio.run(scenario()) <= EXPIRE_S


@pytest.mark.parametrize("operation", ["get", "set"])
def test_redis_connection_failure_becomes_cache_error(operation: str) -> None:
    cache = RedisCache(_disconnected())

    with pytest.raises(CacheError):
        if operation == "get":
            asyncio.run(cache.get(KEY))
        else:
            asyncio.run(cache.set(KEY, "value", EXPIRE_S))


@pytest.mark.parametrize("operation", ["get", "set"])
def test_redis_timeout_becomes_cache_error(monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    async def time_out(*args: Any, **kwargs: Any) -> None:
        raise RedisTimeoutError("timed out")

    client = _fake()
    monkeypatch.setattr(client, operation, time_out)
    cache = RedisCache(client)

    with pytest.raises(CacheError):
        if operation == "get":
            asyncio.run(cache.get(KEY))
        else:
            asyncio.run(cache.set(KEY, "value", EXPIRE_S))


def test_redis_cache_error_does_not_carry_url() -> None:
    cache = RedisCache(_disconnected())

    with pytest.raises(CacheError) as excinfo:
        asyncio.run(cache.get(KEY))

    assert "redis://" not in str(excinfo.value)


def test_redis_client_has_timeouts() -> None:
    async def scenario() -> dict[str, Any]:
        client = build_redis_client(DUMMY_URL, 1.5)
        options = dict(client.connection_pool.connection_kwargs)
        await client.aclose()
        return options

    options = asyncio.run(scenario())

    assert options["socket_timeout"] == 1.5
    assert options["socket_connect_timeout"] == 1.5
    assert options["decode_responses"] is True


def test_redis_non_text_value_becomes_cache_error() -> None:
    async def scenario() -> None:
        # 文字列に直さない設定のクライアントは、バイト列を返す。
        client = fakeredis.FakeAsyncRedis()
        await client.set(KEY, "value")
        await RedisCache(client).get(KEY)

    with pytest.raises(CacheError):
        asyncio.run(scenario())


def test_redis_close_does_not_raise() -> None:
    asyncio.run(RedisCache(_fake()).close())
