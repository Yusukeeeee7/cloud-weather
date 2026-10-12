"""取得した生データ（応答のまま）の置き場所。あれば読み、なければ取得して保存する。"""

import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.cities import City

_SAFE_PART = re.compile(r"[a-z0-9_]+")


def raw_path(root: Path, source: str, city: City, year: int, suffix: str) -> Path:
    """`<root>/<source>/<city>_<year>.<suffix>`。名前は決まった値からだけ作る。"""
    for part in (source, suffix):
        if _SAFE_PART.fullmatch(part) is None:
            raise ValueError("source and suffix must be lowercase letters, digits or underscores")
    return root / source / f"{City(city).value}_{int(year)}.{suffix}"


async def load_or_fetch(path: Path, fetch: Callable[[], Awaitable[str]]) -> str:
    """保存済みならそれを返す（取得しない）。なければ取得し、応答のまま保存してから返す。"""
    if path.exists():
        return path.read_bytes().decode("utf-8")
    text = await fetch()
    if not text.strip():
        raise ValueError("fetched body is empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    # 途中まで書いたファイルを残さないよう、別の名前で書いてから置き換える。
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(text.encode("utf-8"))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return text
