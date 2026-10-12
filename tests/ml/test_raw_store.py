import asyncio
import shutil
from pathlib import Path

import pytest

from app.cities import City
from app.errors import UpstreamError
from ml.raw_store import load_or_fetch, raw_path
from tests.ml.refs import RAW_ROOT, metar_text


class _Fetcher:
    """呼ばれた回数を数える、取得の代わり。"""

    def __init__(self, result: str | Exception) -> None:
        self.result = result
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*") if path.is_file())


def test_raw_path_layout(tmp_path: Path) -> None:
    assert raw_path(tmp_path, "iem", City.TOKYO, 2025, "csv") == tmp_path / "iem" / "tokyo_2025.csv"
    assert (
        raw_path(tmp_path, "open_meteo_archive", City.BERLIN, 2018, "json")
        == tmp_path / "open_meteo_archive" / "berlin_2018.json"
    )


@pytest.mark.parametrize(
    ("source", "suffix"),
    [("../iem", "csv"), ("iem/x", "csv"), ("iem", "../csv"), ("", "csv"), ("iem", "")],
)
def test_raw_path_rejects_path_like_parts(tmp_path: Path, source: str, suffix: str) -> None:
    with pytest.raises(ValueError):
        raw_path(tmp_path, source, City.TOKYO, 2025, suffix)


def test_raw_store_reads_existing_file_without_fetching(tmp_path: Path) -> None:
    # fixture は生データと同じ並びで置いてある（ノートブックのサンプル実行と同じ読み方）。
    # 実装が壊れていても fixture を書き換えないよう、写しを読む。
    source = raw_path(RAW_ROOT, "iem", City.TOKYO, 2025, "csv")
    path = raw_path(tmp_path, "iem", City.TOKYO, 2025, "csv")
    path.parent.mkdir(parents=True)
    shutil.copyfile(source, path)
    fetch = _Fetcher("should not be used")

    text = asyncio.run(load_or_fetch(path, fetch))

    assert text == metar_text("tokyo")
    assert fetch.calls == 0
    assert path.read_bytes() == source.read_bytes()


def test_raw_store_fetches_and_saves_when_missing(tmp_path: Path) -> None:
    path = raw_path(tmp_path, "iem", City.BERLIN, 2025, "csv")
    body = "station,valid\nEDDB,2025-01-15 00:20\n"
    fetch = _Fetcher(body)

    first = asyncio.run(load_or_fetch(path, fetch))
    second = asyncio.run(load_or_fetch(path, fetch))

    assert first == second == body
    assert fetch.calls == 1
    # 応答のまま保存する（改行を変えない）。
    assert path.read_bytes() == body.encode("utf-8")
    assert _files(tmp_path) == [path]


def test_raw_store_keeps_non_ascii_text(tmp_path: Path) -> None:
    path = raw_path(tmp_path, "open_meteo_archive", City.TOKYO, 2025, "json")
    body = '{"hourly_units": {"temperature_2m": "°C"}}'

    asyncio.run(load_or_fetch(path, _Fetcher(body)))

    assert asyncio.run(load_or_fetch(path, _Fetcher("unused"))) == body


@pytest.mark.parametrize("failure", [UpstreamError("failed"), RuntimeError("boom")])
def test_raw_store_does_not_save_failed_fetch(tmp_path: Path, failure: Exception) -> None:
    path = raw_path(tmp_path, "iem", City.TOKYO, 2025, "csv")

    with pytest.raises(type(failure)):
        asyncio.run(load_or_fetch(path, _Fetcher(failure)))

    assert not path.exists()
    assert _files(tmp_path) == []


@pytest.mark.parametrize("body", ["", "   \n"])
def test_raw_store_does_not_save_empty_body(tmp_path: Path, body: str) -> None:
    path = raw_path(tmp_path, "iem", City.TOKYO, 2025, "csv")

    with pytest.raises(ValueError):
        asyncio.run(load_or_fetch(path, _Fetcher(body)))

    assert _files(tmp_path) == []


def test_raw_store_refetches_after_failure(tmp_path: Path) -> None:
    path = raw_path(tmp_path, "iem", City.TOKYO, 2025, "csv")
    with pytest.raises(UpstreamError):
        asyncio.run(load_or_fetch(path, _Fetcher(UpstreamError("failed"))))
    fetch = _Fetcher("station,valid\n")

    text = asyncio.run(load_or_fetch(path, fetch))

    assert text == "station,valid\n"
    assert fetch.calls == 1
