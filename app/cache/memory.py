import time
from collections.abc import Callable

MonotonicClock = Callable[[], float]


class MemoryCache:
    """プロセス内のキャッシュ。再起動で消え、ワーカーごとに別になる。"""

    def __init__(self, clock: MonotonicClock = time.monotonic) -> None:
        self._clock = clock
        # 値と、期限（時計の秒）。
        self._entries: dict[str, tuple[str, float]] = {}

    async def get(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if self._clock() >= expires_at:
            del self._entries[key]
            return None
        return value

    async def set(self, key: str, value: str, expire_s: int) -> None:
        if expire_s <= 0:
            raise ValueError("expire_s must be positive")
        self._entries[key] = (value, self._clock() + expire_s)

    async def close(self) -> None:
        self._entries.clear()
