"""`/weather` の風向（#58）。"""

import asyncio
import copy
from datetime import datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.cache import MemoryCache
from app.cities import City
from app.clients.open_meteo import OpenMeteoClient, build_http_client
from app.config import Settings
from app.services.weather import build_weather_response
from tests.app.cloud_base_fakes import fake_model, row_of, use_model
from tests.conftest import (
    FIXED_NOW,
    FORECAST_URL,
    WIND_NOW,
    FakeClock,
    RawForecast,
    assert_error,
    load_forecast,
    load_wind_forecast,
    mock_ok,
    seed_weather_cache,
)

# spec.md 7 の表「予報の風向」で確認済みの名前。
ITEM = "wind_direction_10m"


def _use_clock(clock: FakeClock) -> None:
    from app.main import app
    from app.routers.weather import get_clock

    app.dependency_overrides[get_clock] = lambda: clock


def _without_direction(raw: RawForecast) -> RawForecast:
    """風向を足す前の形（current・hourly に風向がない）。"""
    changed = copy.deepcopy(raw)
    for section in ("current", "hourly", "current_units", "hourly_units"):
        del changed[section][ITEM]
    return changed


# --- D0：fixture の契約 ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_fixture_has_wind_direction_in_degrees(city: str) -> None:
    raw = load_forecast(city)
    assert raw["current_units"][ITEM] == "°"
    assert raw["hourly_units"][ITEM] == "°"
    assert len(raw["hourly"][ITEM]) == len(raw["hourly"]["time"])


# --- D1：取得する項目 ---


def test_client_requests_wind_direction(open_meteo: respx.MockRouter) -> None:
    route = mock_ok(open_meteo, load_forecast("tokyo"))
    settings = Settings(_env_file=None)

    async def fetch() -> None:
        async with build_http_client(settings) as http:
            await OpenMeteoClient(http, settings).fetch_forecast(City.TOKYO)

    asyncio.run(fetch())

    # 現在・時間ごとの両方で、同じ 1 回の呼び出しで取る。
    params = route.calls.last.request.url.params
    assert ITEM in params["current"].split(",")
    assert ITEM in params["hourly"].split(",")
    assert route.call_count == 1


# --- D2・D3：応答の値 ---


@pytest.mark.parametrize("city", [City.TOKYO, City.BERLIN])
def test_current_has_wind_direction(city: City) -> None:
    raw = load_forecast(city.value)

    response = build_weather_response(city, raw, FIXED_NOW)

    assert response.current.wind_direction_deg == raw["current"][ITEM]


@pytest.mark.parametrize("city", [City.TOKYO, City.BERLIN])
def test_hourly_has_wind_direction(city: City) -> None:
    raw = load_forecast(city.value)

    response = build_weather_response(city, raw, FIXED_NOW)

    assert len(response.hourly) == 24
    for hour in response.hourly:
        assert hour.wind_direction_deg == raw["hourly"][ITEM][row_of(raw, hour.time)]


def test_weather_returns_wind_direction(client: TestClient, open_meteo: respx.MockRouter) -> None:
    raw = load_forecast("tokyo")
    mock_ok(open_meteo, raw)

    body = client.get("/weather", params={"city": "tokyo"}).json()

    assert body["current"]["wind_direction_deg"] == raw["current"][ITEM]
    first = datetime.fromisoformat(body["hourly"][0]["time"])
    assert body["hourly"][0]["wind_direction_deg"] == raw["hourly"][ITEM][row_of(raw, first)]


# --- D4・D5：欠け・null・型違いは 502（欠けと null は test_weather_service・_forecast の一覧） ---


@pytest.mark.parametrize("value", ["202", True])
def test_current_wind_direction_wrong_type_is_502(
    client: TestClient, open_meteo: respx.MockRouter, value: object
) -> None:
    raw = load_forecast("tokyo")
    raw["current"][ITEM] = value
    mock_ok(open_meteo, raw)

    response = client.get("/weather", params={"city": "tokyo"})

    assert_error(response, 502, "upstream_error")


@pytest.mark.parametrize("value", ["202", True])
def test_hourly_wind_direction_wrong_type_is_502(
    client: TestClient, open_meteo: respx.MockRouter, value: object
) -> None:
    raw = load_forecast("tokyo")
    first = FIXED_NOW.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    raw["hourly"][ITEM][row_of(raw, first) + 5] = value
    mock_ok(open_meteo, raw)

    response = client.get("/weather", params={"city": "tokyo"})

    assert_error(response, 502, "upstream_error")


def test_hourly_wind_direction_short_column_is_502(
    client: TestClient, open_meteo: respx.MockRouter
) -> None:
    # 列の長さが時刻と違う（返す範囲の途中で切れている）。
    raw = load_forecast("tokyo")
    first = FIXED_NOW.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    raw["hourly"][ITEM] = raw["hourly"][ITEM][: row_of(raw, first) + 10]
    mock_ok(open_meteo, raw)

    response = client.get("/weather", params={"city": "tokyo"})

    assert_error(response, 502, "upstream_error")


def test_wind_direction_fractional_value_is_accepted() -> None:
    # 公式に整数とは書かれていないので、小数も受ける（#58 の計画の決定 4）。
    raw = load_forecast("tokyo")
    raw["current"][ITEM] = 202.5

    response = build_weather_response(City.TOKYO, raw, FIXED_NOW)

    assert response.current.wind_direction_deg == 202.5


# --- D7・D8：風向のない保存値 ---


def test_weather_refetches_when_cached_entry_lacks_direction(
    client: TestClient, open_meteo: respx.MockRouter
) -> None:
    # 風向を足す前の `/weather` の応答（#25 の追加の fixture）が、TTL の内で保存されている場合。
    clock = FakeClock(WIND_NOW)
    _use_clock(clock)
    seed_weather_cache(client, "tokyo", load_wind_forecast("tokyo"), WIND_NOW)
    raw = load_forecast("tokyo")
    route = mock_ok(open_meteo, raw)

    clock.now = WIND_NOW + timedelta(minutes=5)
    first = client.get("/weather", params={"city": "tokyo"})
    again = client.get("/weather", params={"city": "tokyo"})

    assert first.status_code == 200
    assert first.json()["cached"] is False
    assert first.json()["current"]["wind_direction_deg"] == raw["current"][ITEM]
    # 呼び直した応答は保存され、次は外部APIを呼ばない。
    assert again.json()["cached"] is True
    assert route.call_count == 1


def test_weather_old_entry_without_direction_and_upstream_failure_is_502(
    client: TestClient, open_meteo: respx.MockRouter
) -> None:
    # 風向のない保存値は、stale としても返さない。
    clock = FakeClock(WIND_NOW)
    _use_clock(clock)
    seed_weather_cache(client, "tokyo", load_wind_forecast("tokyo"), WIND_NOW)
    open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(500))

    clock.now = WIND_NOW + timedelta(minutes=20)
    response = client.get("/weather", params={"city": "tokyo"})

    assert_error(response, 502, "upstream_error")


# --- D9：ほかのエンドポイントは変わらない（Red にならない） ---

OTHER_PATHS = [
    "/cloud-base",
    "/cloud-base/forecast",
    "/cloud-base/history",
    "/cloud-history",
    "/sunshine",
]


@pytest.mark.parametrize("path", OTHER_PATHS)
@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_other_endpoints_unchanged_with_direction(
    client: TestClient, open_meteo: respx.MockRouter, path: str, city: str
) -> None:
    from app.main import app
    from app.routers.weather import get_cache

    fake, _ = fake_model(850.0)
    use_model(fake)
    _use_clock(FakeClock(FIXED_NOW))
    raw = load_forecast(city)
    route = mock_ok(open_meteo, raw)

    # 保存値を使わないように、それぞれ空のキャッシュで取る。
    app.dependency_overrides[get_cache] = lambda: MemoryCache()
    with_direction = client.get(path, params={"city": city})
    route.mock(return_value=httpx.Response(200, json=_without_direction(raw)))
    without_direction = client.get(path, params={"city": city})

    assert with_direction.status_code == without_direction.status_code == 200
    assert with_direction.json() == without_direction.json()
    assert route.call_count == 2
