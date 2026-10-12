from typing import Protocol


class CacheError(Exception):
    """キャッシュの読み書きに失敗した。"""


class Cache(Protocol):
    """キャッシュの共通インターフェース。値は文字列（JSON）で、期限は秒。"""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, expire_s: int) -> None: ...

    async def close(self) -> None: ...
