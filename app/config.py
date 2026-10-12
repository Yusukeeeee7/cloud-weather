from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """環境変数から読む設定。既定値は docs/spec.md の値。"""

    open_meteo_base_url: str = "https://api.open-meteo.com"
    open_meteo_connect_timeout_s: float = Field(default=3.0, gt=0)
    open_meteo_total_timeout_s: float = Field(default=10.0, gt=0)
    log_level: LogLevel = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
