from app.cache.base import Cache
from app.cache.memory import MemoryCache
from app.cache.redis import RedisCache, build_redis_client
from app.config import Settings


def build_cache(settings: Settings) -> Cache:
    if settings.cache_backend == "memory":
        return MemoryCache()
    if settings.redis_url is None:
        raise ValueError("REDIS_URL is required when CACHE_BACKEND is redis")
    url = settings.redis_url.get_secret_value()
    return RedisCache(build_redis_client(url, settings.redis_timeout_s))
