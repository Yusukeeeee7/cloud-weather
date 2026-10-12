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
# 秒未満を含む時刻にして、レスポンスで切り捨てられることも確かめられるようにする。
FIXED_NOW = datetime(2026, 10, 12, 13, 41, 2, 123456, tzinfo=UTC)

RawForecast = dict[str, Any]


def load_forecast(city: str) -> RawForecast:
    path = FIXTURES_DIR / "open_meteo" / f"forecast_current_{city}.json"
    raw: RawForecast = json.loads(path.read_text(encoding="utf-8"))
    return raw


@pytest.fixture
def forecast() -> Callable[[str], RawForecast]:
    return load_forecast


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
