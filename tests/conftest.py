import copy
import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# fixture を取得した時刻（2026-10-12T15:02:12Z）の直後にする。
# hourly の 24 件は時計に依存するため、fixture を取り直したらここも変える。
# 秒未満を含む時刻にして、レスポンスで切り捨てられることも確かめられるようにする。
FIXED_NOW = datetime(2026, 10, 12, 15, 2, 30, 123456, tzinfo=UTC)

# /cloud-base 用の fixture（hourly に 4 項目を足した応答）を取得した時刻の直後。
# 東京 2026-10-13T14:16:25Z、ベルリン 14:16:29Z。
CLOUD_BASE_NOW = datetime(2026, 10, 13, 14, 16, 30, 123456, tzinfo=UTC)

# 過去 24 時間を含む fixture（#15）を取得した時刻（2 都市とも 2026-10-14T09:18:03Z）の直後。
PAST_NOW = datetime(2026, 10, 14, 9, 18, 5, 123456, tzinfo=UTC)

# 日差しの 3 項目を含む fixture（#15）を取得した時刻（2026-10-14T12:20:49Z〜12:21:02Z）の直後。
SUN_NOW = datetime(2026, 10, 14, 12, 21, 5, 123456, tzinfo=UTC)

RawForecast = dict[str, Any]


class FakeClock:
    """テストで時刻を進めるための時計。`now` を書き換えると、次の呼び出しからその時刻を返す。"""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _load(name: str) -> RawForecast:
    path = FIXTURES_DIR / "open_meteo" / name
    raw: RawForecast = json.loads(path.read_text(encoding="utf-8"))
    return raw


def load_forecast(city: str) -> RawForecast:
    return _load(f"forecast_{city}.json")


def load_forecast_iso8601(city: str) -> RawForecast:
    return _load(f"forecast_{city}_iso8601.json")


def load_cloud_base_forecast(city: str) -> RawForecast:
    return _load(f"forecast_{city}_cloud_base.json")


def load_past_forecast(city: str) -> RawForecast:
    return _load(f"forecast_{city}_past.json")


def load_sun_forecast(city: str) -> RawForecast:
    return _load(f"forecast_{city}_sun.json")


@pytest.fixture
def forecast() -> Callable[[str], RawForecast]:
    return load_forecast


@pytest.fixture
def forecast_iso8601() -> Callable[[str], RawForecast]:
    # 同じ時刻に、時刻形式だけ変えて取得した応答。現地の日付の期待値として使う。
    return load_forecast_iso8601


@pytest.fixture(autouse=True)
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """リトライの合間の待ちを、記録するだけにする（テストで実際に待たない）。待った秒の一覧を返す。"""
    recorded: list[float] = []

    async def record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr("app.clients.open_meteo.wait", record)
    return recorded


@pytest.fixture
def open_meteo() -> Iterator[respx.MockRouter]:
    # モックしていない通信が起きたらテストを失敗させる（外部APIを実際に呼ばない）。
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


@pytest.fixture
def client(open_meteo: respx.MockRouter) -> Iterator[TestClient]:
    from app.main import app
    from app.routers.weather import get_clock

    app.dependency_overrides[get_clock] = lambda: lambda: FIXED_NOW
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- 外部APIのモックと応答の確認（#15 のテストで共有する） ---


def iso(at: datetime) -> str:
    """応答の時刻の書き方（UTC、末尾 Z、秒まで）。"""
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def mock_ok(open_meteo: respx.MockRouter, raw: RawForecast) -> respx.Route:
    return open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=raw))


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    """spec.md「5. 共通」のエラー形式で、その HTTP と code であること。"""
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


def without_past_hours(raw: RawForecast) -> RawForecast:
    """過去の時間を足す前の形（hourly が取得時の正時から始まる）。fixture の先頭 24 行を除く。"""
    changed = copy.deepcopy(raw)
    changed["hourly"] = {name: column[24:] for name, column in raw["hourly"].items()}
    return changed
