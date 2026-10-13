"""#12 推論API：`GET /cloud-base`（外部APIは respx でモックする）。"""

import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import fakeredis
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.cache import RedisCache
from app.cities import City
from ml import model
from tests.app.cloud_base_fakes import (
    CAP_M,
    expected_baseline_m,
    fake_model,
    row_of,
    training_features,
)
from tests.conftest import (
    CLOUD_BASE_NOW,
    FIXED_NOW,
    FORECAST_URL,
    FakeClock,
    RawForecast,
    load_cloud_base_forecast,
    load_forecast,
)

VALID_AT = datetime(2026, 10, 13, 14, 0, tzinfo=UTC)
RESPONSE_KEYS = {"city", "valid_at", "predicted_m", "baseline_m", "model_version"}
# spec.md「3. 対象地点」の値。
COORDINATES = {"tokyo": (35.55, 139.78), "berlin": (52.36, 13.50)}
SIX_HOURS = timedelta(hours=6)


def _mock_ok(open_meteo: respx.MockRouter, raw: RawForecast) -> respx.Route:
    return open_meteo.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=raw))


def _use_clock(clock: FakeClock) -> None:
    from app.main import app
    from app.routers.weather import get_clock

    app.dependency_overrides[get_clock] = lambda: clock


def _use_model(replacement: model.CloudBaseModel | None) -> None:
    from app.main import app
    from app.routers.cloud_base import get_cloud_base_model

    app.dependency_overrides[get_cloud_base_model] = lambda: replacement


def _assert_error(response: httpx.Response, status: int, code: str) -> str:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    message = body["error"]["message"]
    assert isinstance(message, str) and message
    return message


@pytest.fixture
def clock(client: TestClient) -> FakeClock:
    """`/cloud-base` 用の fixture を取得した時刻に合わせた時計。"""
    fake = FakeClock(CLOUD_BASE_NOW)
    _use_clock(fake)
    return fake


# --- 14〜16：正常な応答と city ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_cloud_base_returns_spec_keys_and_types(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    # リポジトリのモデル（起動のときに読み込んだもの）で返す。
    from app.services.cloud_base import MODEL_PATH

    raw = load_cloud_base_forecast(city)
    _mock_ok(open_meteo, raw)
    committed = model.load(MODEL_PATH)
    direct = model.predict_m(committed, training_features(City(city), raw, VALID_AT)).iloc[0]

    response = client.get("/cloud-base", params={"city": city})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESPONSE_KEYS
    assert body["city"] == city
    assert body["valid_at"] == "2026-10-13T14:00:00Z"
    assert type(body["predicted_m"]) is int
    assert type(body["baseline_m"]) is int
    assert body["predicted_m"] == int(direct + 0.5)
    assert 0 <= body["predicted_m"] <= CAP_M
    assert body["baseline_m"] == expected_baseline_m(raw, VALID_AT)
    assert body["model_version"] == committed.model_version
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-lgbm-v\d+", body["model_version"])


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_cloud_base_for_each_city(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    raw = load_cloud_base_forecast(city)
    route = _mock_ok(open_meteo, raw)
    fake, booster = fake_model(850.0, model_version="fake-v7")
    _use_model(fake)

    response = client.get("/cloud-base", params={"city": city})

    assert response.status_code == 200
    assert response.json() == {
        "city": city,
        "valid_at": "2026-10-13T14:00:00Z",
        "predicted_m": 850,
        "baseline_m": expected_baseline_m(raw, VALID_AT),
        "model_version": "fake-v7",
    }
    assert route.call_count == 1
    params = route.calls.last.request.url.params
    assert (float(params["latitude"]), float(params["longitude"])) == COORDINATES[city]
    assert booster.seen[0]["city_code"].tolist() == [list(COORDINATES).index(city)]


def test_cloud_base_city_default_is_tokyo(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    route = _mock_ok(open_meteo, load_cloud_base_forecast("tokyo"))
    fake, _ = fake_model(850.0)
    _use_model(fake)

    response = client.get("/cloud-base")

    assert response.status_code == 200
    assert response.json()["city"] == "tokyo"
    params = route.calls.last.request.url.params
    assert (float(params["latitude"]), float(params["longitude"])) == COORDINATES["tokyo"]


@pytest.mark.parametrize("city", ["", "osaka", "TOKYO", " tokyo", "tokyo,berlin", "../etc"])
def test_cloud_base_invalid_city_is_422(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    route = _mock_ok(open_meteo, load_cloud_base_forecast("tokyo"))
    fake, booster = fake_model(850.0)
    _use_model(fake)

    response = client.get("/cloud-base", params={"city": city})

    message = _assert_error(response, 422, "invalid_city")
    # 入力値は応答に含めない。外部APIも呼ばない。
    if city in ("osaka", "../etc"):
        assert city not in message
    assert route.call_count == 0
    assert booster.seen == []


# --- 17〜19：モデルが読めない ---


@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_model_unavailable_returns_503(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, city: str
) -> None:
    route = _mock_ok(open_meteo, load_cloud_base_forecast(city))
    _use_model(None)

    response = client.get("/cloud-base", params={"city": city})

    message = _assert_error(response, 503, "model_unavailable")
    # パス・ファイル名・例外の文面を応答に出さない。
    for word in ("joblib", "models", "/", "\\", "Error", "Traceback"):
        assert word not in message
    # モデルがないのに、外部APIの枠を使わない。
    assert route.call_count == 0


def test_invalid_city_wins_over_model_unavailable(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    _use_model(None)

    response = client.get("/cloud-base", params={"city": "osaka"})

    _assert_error(response, 422, "invalid_city")


def _started_client(open_meteo: respx.MockRouter) -> Iterator[TestClient]:
    from app.main import app
    from app.routers.weather import get_clock

    app.dependency_overrides[get_clock] = lambda: lambda: CLOUD_BASE_NOW
    try:
        with TestClient(app) as started:
            yield started
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("content", [None, b"", b"this is not a model"])
def test_app_starts_without_model_and_other_endpoints_work(
    open_meteo: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    content: bytes | None,
) -> None:
    # ファイルがない・空・壊れている、のどれでも起動は続ける。
    path = tmp_path / "secret-directory" / "cloud_base.joblib"
    if content is not None:
        path.parent.mkdir()
        path.write_bytes(content)
    monkeypatch.setattr("app.services.cloud_base.MODEL_PATH", path)
    route = _mock_ok(open_meteo, load_cloud_base_forecast("tokyo"))

    with caplog.at_level(logging.WARNING):
        for started in _started_client(open_meteo):
            health = started.get("/health")
            daylight = started.get("/daylight", params={"city": "berlin", "date": "2026-12-21"})
            weather = started.get("/weather", params={"city": "tokyo"})
            calls_before = route.call_count
            cloud_base = started.get("/cloud-base", params={"city": "tokyo"})

    assert (health.status_code, daylight.status_code, weather.status_code) == (200, 200, 200)
    _assert_error(cloud_base, 503, "model_unavailable")
    assert route.call_count == calls_before == 1
    # 起動のときに警告を 1 行残す。パスは出さない。
    warnings = [record for record in caplog.records if "model" in record.getMessage().lower()]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    assert "secret-directory" not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_app_loads_committed_model_once_at_startup(
    open_meteo: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 読み込むのは起動のときの 1 回だけ（リクエストのたびに読まない）。パスは定数。
    from app.services import cloud_base as service

    loaded: list[Path] = []
    real_load = model.load

    def recording_load(path: Path) -> model.CloudBaseModel:
        loaded.append(path)
        return real_load(path)

    monkeypatch.setattr("ml.model.load", recording_load)
    _mock_ok(open_meteo, load_cloud_base_forecast("tokyo"))

    for started in _started_client(open_meteo):
        first = started.get("/cloud-base", params={"city": "tokyo"})
        second = started.get("/cloud-base", params={"city": "tokyo"})

    assert (first.status_code, second.status_code) == (200, 200)
    assert loaded == [service.MODEL_PATH]
    assert service.MODEL_PATH.parts[-2:] == ("models", "cloud_base.joblib")
    assert service.MODEL_PATH.is_file()


# --- 20：外部APIの失敗 ---


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(500),
        httpx.Response(404),
        httpx.Response(429),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=[1, 2, 3]),
        httpx.ConnectTimeout("timeout"),
        httpx.ConnectError("refused"),
    ],
    ids=["500", "404", "429", "not-json", "json-list", "timeout", "connect-error"],
)
def test_cloud_base_upstream_failure_without_cache_is_502(
    client: TestClient,
    open_meteo: respx.MockRouter,
    clock: FakeClock,
    failure: httpx.Response | Exception,
) -> None:
    if isinstance(failure, Exception):
        open_meteo.get(FORECAST_URL).mock(side_effect=failure)
    else:
        open_meteo.get(FORECAST_URL).mock(return_value=failure)
    fake, booster = fake_model(850.0)
    _use_model(fake)

    response = client.get("/cloud-base", params={"city": "tokyo"})

    message = _assert_error(response, 502, "upstream_error")
    assert "open-meteo" not in message.lower()
    assert booster.seen == []


def test_cloud_base_missing_item_in_response_is_502(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    raw = load_cloud_base_forecast("tokyo")
    raw["hourly"]["pressure_msl"][row_of(raw, VALID_AT)] = None
    route = _mock_ok(open_meteo, raw)
    fake, _ = fake_model(850.0)
    _use_model(fake)

    first = client.get("/cloud-base", params={"city": "tokyo"})
    second = client.get("/cloud-base", params={"city": "tokyo"})

    _assert_error(first, 502, "upstream_error")
    _assert_error(second, 502, "upstream_error")
    # 予測に使えない応答は保存しない（次のリクエストで呼び直す）。
    assert route.call_count == 2


# --- 21〜23：キャッシュと stale ---


@pytest.mark.parametrize("order", [("/weather", "/cloud-base"), ("/cloud-base", "/weather")])
@pytest.mark.parametrize("city", ["tokyo", "berlin"])
def test_cloud_base_shares_cache_with_weather(
    client: TestClient,
    open_meteo: respx.MockRouter,
    clock: FakeClock,
    city: str,
    order: tuple[str, str],
) -> None:
    route = _mock_ok(open_meteo, load_cloud_base_forecast(city))
    fake, _ = fake_model(850.0)
    _use_model(fake)

    first = client.get(order[0], params={"city": city})
    clock.now = CLOUD_BASE_NOW + timedelta(minutes=5)
    second = client.get(order[1], params={"city": city})

    assert (first.status_code, second.status_code) == (200, 200)
    assert route.call_count == 1


@pytest.mark.parametrize("order", [("/weather", "/cloud-base"), ("/cloud-base", "/weather")])
def test_cloud_base_shares_redis_cache_with_weather(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock, order: tuple[str, str]
) -> None:
    # 実物の Redis は使わない。保存先を Redis に替えても、同じ保存値を共用すること。
    from app.main import app
    from app.routers.weather import get_cache

    cache = RedisCache(fakeredis.FakeAsyncRedis(decode_responses=True))
    app.dependency_overrides[get_cache] = lambda: cache
    route = _mock_ok(open_meteo, load_cloud_base_forecast("berlin"))
    fake, _ = fake_model(850.0)
    _use_model(fake)

    first = client.get(order[0], params={"city": "berlin"})
    clock.now = CLOUD_BASE_NOW + timedelta(minutes=5)
    second = client.get(order[1], params={"city": "berlin"})

    assert (first.status_code, second.status_code) == (200, 200)
    assert route.call_count == 1


def test_cloud_base_second_request_is_cached_and_refetches_after_ttl(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    route = _mock_ok(open_meteo, load_cloud_base_forecast("tokyo"))
    fake, _ = fake_model(850.0)
    _use_model(fake)

    first = client.get("/cloud-base", params={"city": "tokyo"})
    clock.now = CLOUD_BASE_NOW + timedelta(minutes=14, seconds=59)
    hit = client.get("/cloud-base", params={"city": "tokyo"})
    calls_after_hit = route.call_count
    # TTL（15 分）ちょうどから呼び直す。
    clock.now = CLOUD_BASE_NOW + timedelta(minutes=15)
    miss = client.get("/cloud-base", params={"city": "tokyo"})

    assert (first.status_code, hit.status_code, miss.status_code) == (200, 200, 200)
    assert hit.json() == first.json()
    assert calls_after_hit == 1
    assert route.call_count == 2


def test_cloud_base_selects_row_again_when_served_from_cache(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    # 14:55 に取得した保存値を 15:05 に使うときは、15:00 の行で予測する。
    raw = load_cloud_base_forecast("tokyo")
    route = _mock_ok(open_meteo, raw)
    fake, booster = fake_model(850.0)
    _use_model(fake)
    clock.now = datetime(2026, 10, 13, 14, 55, tzinfo=UTC)
    first = client.get("/cloud-base", params={"city": "tokyo"})

    clock.now = datetime(2026, 10, 13, 15, 5, tzinfo=UTC)
    second = client.get("/cloud-base", params={"city": "tokyo"})

    assert route.call_count == 1
    assert first.json()["valid_at"] == "2026-10-13T14:00:00Z"
    assert second.json()["valid_at"] == "2026-10-13T15:00:00Z"
    later = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
    assert second.json()["baseline_m"] == expected_baseline_m(raw, later)
    expected = raw["hourly"]["pressure_msl"][row_of(raw, later)]
    assert booster.seen[-1]["pressure_msl_hpa"].tolist() == [expected]


def test_cloud_base_refetches_when_cached_entry_lacks_new_items(
    client: TestClient, open_meteo: respx.MockRouter
) -> None:
    # 4 項目を足す前の応答（既存の fixture の形）が保存されている場合。
    # 既存の fixture の取得時刻（FIXED_NOW）の正時 15:00Z は、新しい東京の fixture の先頭の行。
    clock = FakeClock(FIXED_NOW)
    _use_clock(clock)
    route = _mock_ok(open_meteo, load_forecast("tokyo"))
    fake, _ = fake_model(850.0)
    _use_model(fake)
    weather = client.get("/weather", params={"city": "tokyo"})
    assert (weather.status_code, route.call_count) == (200, 1)

    new = load_cloud_base_forecast("tokyo")
    route.mock(return_value=httpx.Response(200, json=new))
    clock.now = FIXED_NOW + timedelta(minutes=5)
    cloud_base = client.get("/cloud-base", params={"city": "tokyo"})
    again = client.get("/cloud-base", params={"city": "tokyo"})

    assert cloud_base.status_code == 200
    assert cloud_base.json()["valid_at"] == "2026-10-12T15:00:00Z"
    assert cloud_base.json()["baseline_m"] == expected_baseline_m(
        new, datetime(2026, 10, 12, 15, 0, tzinfo=UTC)
    )
    # 呼び直した応答は保存され、次は外部APIを呼ばない。
    assert again.json() == cloud_base.json()
    assert route.call_count == 2


def test_cloud_base_old_entry_and_upstream_failure_is_502(
    client: TestClient, open_meteo: respx.MockRouter
) -> None:
    # 4 項目のない保存値は、stale としても使えない。
    clock = FakeClock(FIXED_NOW)
    _use_clock(clock)
    route = _mock_ok(open_meteo, load_forecast("tokyo"))
    fake, _ = fake_model(850.0)
    _use_model(fake)
    client.get("/weather", params={"city": "tokyo"})

    route.mock(return_value=httpx.Response(500))
    clock.now = FIXED_NOW + timedelta(minutes=5)
    response = client.get("/cloud-base", params={"city": "tokyo"})

    _assert_error(response, 502, "upstream_error")


def test_cloud_base_uses_stale_cache_when_upstream_fails(
    client: TestClient, open_meteo: respx.MockRouter, clock: FakeClock
) -> None:
    raw = load_cloud_base_forecast("tokyo")
    route = _mock_ok(open_meteo, raw)
    fake, booster = fake_model(850.0)
    _use_model(fake)
    client.get("/cloud-base", params={"city": "tokyo"})
    route.mock(return_value=httpx.Response(500))

    clock.now = CLOUD_BASE_NOW + timedelta(hours=2)
    stale = client.get("/cloud-base", params={"city": "tokyo"})
    # 上限（6 時間）ちょうどは返す。過ぎたら 502。
    clock.now = CLOUD_BASE_NOW + SIX_HOURS
    at_limit = client.get("/cloud-base", params={"city": "tokyo"})
    clock.now = CLOUD_BASE_NOW + SIX_HOURS + timedelta(seconds=1)
    too_old = client.get("/cloud-base", params={"city": "tokyo"})

    assert stale.status_code == 200
    # 応答のキーは増やさない。予測する時刻は、いまの時刻で選び直す。
    assert set(stale.json()) == RESPONSE_KEYS
    assert stale.json()["valid_at"] == "2026-10-13T16:00:00Z"
    later = VALID_AT + timedelta(hours=2)
    assert stale.json()["baseline_m"] == expected_baseline_m(raw, later)
    seen_at_stale = booster.seen[1]
    assert seen_at_stale["temperature_c"].tolist() == [
        raw["hourly"]["temperature_2m"][row_of(raw, later)]
    ]
    assert at_limit.status_code == 200
    assert at_limit.json()["valid_at"] == "2026-10-13T20:00:00Z"
    _assert_error(too_old, 502, "upstream_error")


# --- 24：OpenAPI ---


def test_openapi_documents_cloud_base(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    operation = schema["paths"]["/cloud-base"]["get"]
    assert {"200", "422", "502", "503"} <= set(operation["responses"])
    parameters = {parameter["name"] for parameter in operation["parameters"]}
    assert parameters == {"city"}
    properties = schema["components"]["schemas"]["CloudBaseResponse"]["properties"]
    assert set(properties) == RESPONSE_KEYS
    # 上限（1,524 m）の意味は、応答の項目を増やさずに説明に書く。
    assert "1524" in properties["predicted_m"]["description"]
    assert "1524" in properties["baseline_m"]["description"]
