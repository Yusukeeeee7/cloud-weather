import asyncio

import pytest

from app.cache import MemoryCache

KEY = "weather:tokyo"
EXPIRE_S = 900


class _Ticker:
    """単調に進む秒を返す時計。`seconds` を書き換えて時刻を進める。"""

    def __init__(self) -> None:
        self.seconds = 1000.0

    def __call__(self) -> float:
        return self.seconds


def test_memory_get_missing_returns_none() -> None:
    cache = MemoryCache()

    assert asyncio.run(cache.get(KEY)) is None


def test_memory_set_then_get() -> None:
    async def scenario() -> tuple[str | None, str | None, str | None]:
        cache = MemoryCache()
        await cache.set(KEY, "first", EXPIRE_S)
        await cache.set("weather:berlin", "other", EXPIRE_S)
        first = await cache.get(KEY)
        await cache.set(KEY, "second", EXPIRE_S)
        return first, await cache.get(KEY), await cache.get("weather:berlin")

    assert asyncio.run(scenario()) == ("first", "second", "other")


def test_memory_expires_after_expire_s() -> None:
    ticker = _Ticker()

    async def read_after(elapsed_s: float) -> str | None:
        ticker.seconds = 1000.0 + elapsed_s
        return await cache.get(KEY)

    cache = MemoryCache(clock=ticker)
    asyncio.run(cache.set(KEY, "value", EXPIRE_S))

    assert asyncio.run(read_after(EXPIRE_S - 1)) == "value"
    assert asyncio.run(read_after(EXPIRE_S)) is None
    assert asyncio.run(read_after(EXPIRE_S + 1)) is None


def test_memory_expired_entry_can_be_set_again() -> None:
    ticker = _Ticker()
    cache = MemoryCache(clock=ticker)
    asyncio.run(cache.set(KEY, "old", EXPIRE_S))
    ticker.seconds += EXPIRE_S

    asyncio.run(cache.set(KEY, "new", EXPIRE_S))
    ticker.seconds += EXPIRE_S - 1

    assert asyncio.run(cache.get(KEY)) == "new"


@pytest.mark.parametrize("expire_s", [0, -1])
def test_memory_rejects_non_positive_expire(expire_s: int) -> None:
    cache = MemoryCache()

    with pytest.raises(ValueError):
        asyncio.run(cache.set(KEY, "value", expire_s))

    assert asyncio.run(cache.get(KEY)) is None


def test_memory_close_does_not_raise() -> None:
    asyncio.run(MemoryCache().close())
