from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
CacheBackend = Literal["memory", "redis"]


class Settings(BaseSettings):
    """環境変数から読む設定。既定値は docs/spec.md の値。"""

    open_meteo_base_url: str = "https://api.open-meteo.com"
    open_meteo_connect_timeout_s: float = Field(default=3.0, gt=0)
    open_meteo_total_timeout_s: float = Field(default=10.0, gt=0)
    log_level: LogLevel = "INFO"
    # 既定はメモリ（Redis なしで起動・テストできるようにする）。
    cache_backend: CacheBackend = "memory"
    cache_ttl_s: int = Field(default=900, gt=0)
    # パスワードを含みうるので、表示・ログに値が出ない型で持つ。
    redis_url: SecretStr | None = None
    redis_timeout_s: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def _require_redis_url(self) -> Self:
        if self.cache_backend == "redis" and not (
            self.redis_url and self.redis_url.get_secret_value()
        ):
            raise ValueError("REDIS_URL is required when CACHE_BACKEND is redis")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
