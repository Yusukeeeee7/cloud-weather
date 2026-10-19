import re
from datetime import UTC, date, datetime

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from tests.solar_refs import TOLERANCE, open_meteo_sun_times

UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
TOP_LEVEL_KEYS = {
    "city",
    "date",
    "sunrise",
    "sunset",
    "twilight",
    "daylight_hours",
    "night_hours",
    "dark_hours",
    "solar_noon",
    "solar_noon_elevation_deg",
    "method",
}
TWILIGHT_KINDS = {"civil", "nautical", "astronomical"}


def _parse(value: str) -> datetime:
    assert UTC_Z.match(value)
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _assert_error(response: httpx.Response, code: str) -> str:
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    message = body["error"]["message"]
    assert isinstance(message, str) and message
    return message


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_daylight_returns_200_and_spec_shape(client: TestClient, city: str) -> None:
    response = client.get("/daylight", params={"city": city, "date": "2026-12-21"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == TOP_LEVEL_KEYS
    assert set(body["twilight"]) == TWILIGHT_KINDS
    assert body["city"] == city
    assert body["date"] == "2026-12-21"
    assert body["method"] == "noaa-solar-calculator"
    for key in ("sunrise", "sunset", "solar_noon"):
        assert UTC_Z.match(body[key])
    for kind in TWILIGHT_KINDS:
        assert set(body["twilight"][kind]) == {"dawn", "dusk"}
        assert UTC_Z.match(body["twilight"][kind]["dawn"])
        assert UTC_Z.match(body["twilight"][kind]["dusk"])
    for key in ("daylight_hours", "night_hours", "dark_hours", "solar_noon_elevation_deg"):
        assert isinstance(body[key], float)
    assert body["daylight_hours"] + body["night_hours"] == pytest.approx(24.0)


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_daylight_matches_open_meteo_within_2_minutes(client: TestClient, city: str) -> None:
    # 受け入れ条件：Open-Meteo の日の出入りと ±2 分以内（API の応答で確かめる）。
    for day, (sunrise, sunset) in open_meteo_sun_times(f"forecast_{city}.json", city).items():
        body = client.get("/daylight", params={"city": city, "date": day.isoformat()}).json()

        assert body["date"] == day.isoformat()
        assert abs(_parse(body["sunrise"]) - sunrise) <= TOLERANCE
        assert abs(_parse(body["sunset"]) - sunset) <= TOLERANCE


@pytest.mark.parametrize(("city", "expected"), [("tokyo", "2026-10-20"), ("berlin", "2026-10-19")])
def test_daylight_missing_date_uses_local_today(
    client: TestClient, city: str, expected: str
) -> None:
    # conftest の時計は 2026-10-19T18:26:00Z。東京は現地の日付が 10-20 に進んでいる。
    response = client.get("/daylight", params={"city": city})

    assert response.status_code == 200
    assert response.json()["date"] == expected


def test_daylight_missing_city_defaults_to_tokyo(client: TestClient) -> None:
    response = client.get("/daylight", params={"date": "2026-12-21"})

    assert response.status_code == 200
    assert response.json()["city"] == "tokyo"


def test_daylight_without_parameters(client: TestClient) -> None:
    response = client.get("/daylight")

    assert response.status_code == 200
    assert (response.json()["city"], response.json()["date"]) == ("tokyo", "2026-10-20")


def test_daylight_null_twilight_is_returned_as_null(client: TestClient) -> None:
    # ベルリンの夏至：天文薄明が終わらない。エラーにせず null。
    response = client.get("/daylight", params={"city": "berlin", "date": "2026-06-21"})

    assert response.status_code == 200
    twilight = response.json()["twilight"]
    assert twilight["astronomical"] == {"dawn": None, "dusk": None}
    assert UTC_Z.match(twilight["nautical"]["dawn"])
    assert UTC_Z.match(twilight["nautical"]["dusk"])


@pytest.mark.parametrize(
    "city", ["osaka", "Tokyo", "TOKYO", "", " tokyo", "http://example.com", "tokyo,berlin"]
)
def test_daylight_invalid_city_returns_422(client: TestClient, city: str) -> None:
    response = client.get("/daylight", params={"city": city, "date": "2026-12-21"})

    _assert_error(response, "invalid_city")


@pytest.mark.parametrize(
    "value",
    [
        "2026/12/21",
        "20261221",
        "2026-12-21T00:00:00",
        "2026-12-21T00:00:00Z",
        "2026-02-30",
        "2026-13-01",
        "2026-00-10",
        "2026-12-1",
        "26-12-21",
        "",
        "today",
        "1766275200",
        " 2026-12-21",
        "2026-12-21 ",
        "2026-12-21\n",
        "２０２６-12-21",
        "+2026-12-21",
        "2026-W52-1",
        "http://example.com",
    ],
)
def test_daylight_invalid_date_format_returns_422(client: TestClient, value: str) -> None:
    response = client.get("/daylight", params={"city": "berlin", "date": value})

    message = _assert_error(response, "invalid_date")
    # 入力値は応答に含めない。
    if value.strip():
        assert value.strip() not in message


@pytest.mark.parametrize(
    ("value", "expected_status"),
    [
        ("1900-01-01", 200),
        ("2100-12-31", 200),
        ("1899-12-31", 422),
        ("2101-01-01", 422),
        ("0001-01-01", 422),
        ("9999-12-31", 422),
    ],
)
@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_daylight_date_range_boundaries(
    client: TestClient, city: str, value: str, expected_status: int
) -> None:
    response = client.get("/daylight", params={"city": city, "date": value})

    assert response.status_code == expected_status
    if expected_status == 200:
        body = response.json()
        assert set(body) == TOP_LEVEL_KEYS
        assert body["date"] == value
    else:
        _assert_error(response, "invalid_date")


def test_daylight_invalid_city_and_date_returns_invalid_city(client: TestClient) -> None:
    # 両方が不正なときは invalid_city（2026-10-12 決定）。
    response = client.get("/daylight", params={"city": "osaka", "date": "tomorrow"})

    _assert_error(response, "invalid_city")


class _RecordingCache:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get(self, key: str) -> str | None:
        self.calls.append(("get", key))
        return None

    async def set(self, key: str, value: str, expire_s: int) -> None:
        self.calls.append(("set", key))

    async def close(self) -> None:
        return None


def test_daylight_does_not_call_external_api_or_cache(
    client: TestClient, open_meteo: respx.MockRouter
) -> None:
    # 計算だけで返す（spec.md「6. キャッシュ」：/daylight はキャッシュしない）。
    from app.main import app
    from app.routers.weather import get_cache

    cache = _RecordingCache()
    app.dependency_overrides[get_cache] = lambda: cache

    response = client.get("/daylight", params={"city": "tokyo", "date": "2026-12-21"})

    assert response.status_code == 200
    assert len(open_meteo.calls) == 0
    assert cache.calls == []


@pytest.mark.parametrize("params", [{"city": "osaka"}, {"city": "osaka", "date": "2026-12-21"}])
def test_weather_validation_still_returns_invalid_city(
    client: TestClient, params: dict[str, str]
) -> None:
    # 422 のハンドラを項目ごとに分けても、/weather の誤りは invalid_city のまま。
    response = client.get("/weather", params=params)

    _assert_error(response, "invalid_city")


def test_openapi_includes_daylight(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    operation = schema["paths"]["/daylight"]["get"]
    assert {parameter["name"] for parameter in operation["parameters"]} == {"city", "date"}
    ok = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ok == "#/components/schemas/DaylightResponse"
    error = operation["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
    assert error == "#/components/schemas/ErrorResponse"
    assert set(schema["components"]["schemas"]["DaylightResponse"]["required"]) == TOP_LEVEL_KEYS


def test_daylight_rejects_post(client: TestClient) -> None:
    response = client.post("/daylight", params={"city": "tokyo"})

    assert response.status_code == 405


def test_daylight_same_request_returns_same_result(client: TestClient) -> None:
    params = {"city": "berlin", "date": "2026-03-29"}

    first = client.get("/daylight", params=params)
    second = client.get("/daylight", params=params)

    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json() == second.json()


def test_daylight_date_is_not_shifted_by_the_clock(client: TestClient) -> None:
    # date を指定したら、時計（いまの時刻）に関係なくその日付で返す。
    body = client.get("/daylight", params={"city": "tokyo", "date": "2026-10-14"}).json()

    assert body["date"] == date(2026, 10, 14).isoformat()
