import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# fixture を取得した時刻（2026-10-12T15:02:12Z）の直後にする。
# hourly の 24 件は時計に依存するため、fixture を取り直したらここも変える。
# 秒未満を含む時刻にして、レスポンスで切り捨てられることも確かめられるようにする。
FIXED_NOW = datetime(2026, 10, 12, 15, 2, 30, 123456, tzinfo=UTC)

RawForecast = dict[str, Any]


def _load(name: str) -> RawForecast:
    path = FIXTURES_DIR / "open_meteo" / name
    raw: RawForecast = json.loads(path.read_text(encoding="utf-8"))
    return raw


def load_forecast(city: str) -> RawForecast:
    return _load(f"forecast_{city}.json")


def load_forecast_iso8601(city: str) -> RawForecast:
    return _load(f"forecast_{city}_iso8601.json")


@pytest.fixture
def forecast() -> Callable[[str], RawForecast]:
    return load_forecast


@pytest.fixture
def forecast_iso8601() -> Callable[[str], RawForecast]:
    # 同じ時刻に、時刻形式だけ変えて取得した応答。現地の日付の期待値として使う。
    return load_forecast_iso8601


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
