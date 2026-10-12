import asyncio

import fakeredis
import pytest

from app.cache import MemoryCache, RedisCache, build_cache
from app.config import Settings

# 実在しない接続先。クライアントを作るだけで、接続はしない。
DUMMY_URL = "redis://localhost:6379/0"
CACHE_ENV = ("CACHE_BACKEND", "CACHE_TTL_S", "REDIS_URL", "REDIS_TIMEOUT_S")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CACHE_ENV:
        monkeypatch.delenv(name, raising=False)


def test_build_cache_memory_by_default() -> None:
    cache = build_cache(Settings(_env_file=None))

    assert isinstance(cache, MemoryCache)


def test_build_cache_memory_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    # メモリのときは REDIS_URL があっても使わない。
    monkeypatch.setenv("REDIS_URL", DUMMY_URL)

    assert isinstance(build_cache(Settings(_env_file=None)), MemoryCache)


def test_build_cache_redis_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CACHE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", DUMMY_URL)

    cache = build_cache(Settings(_env_file=None))

    assert isinstance(cache, RedisCache)
    asyncio.run(cache.close())


def test_build_cache_passes_url_and_timeout_to_redis_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 設定のタイムアウトが、実際に作られるクライアントまで届くこと（直書きの値にならない）。
    received: list[tuple[str, float]] = []

    def record(url: str, timeout_s: float) -> fakeredis.FakeAsyncRedis:
        received.append((url, timeout_s))
        return fakeredis.FakeAsyncRedis(decode_responses=True)

    monkeypatch.setattr("app.cache.factory.build_redis_client", record)
    monkeypatch.setenv("CACHE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", DUMMY_URL)
    monkeypatch.setenv("REDIS_TIMEOUT_S", "0.5")

    cache = build_cache(Settings(_env_file=None))

    assert isinstance(cache, RedisCache)
    assert received == [(DUMMY_URL, 0.5)]
