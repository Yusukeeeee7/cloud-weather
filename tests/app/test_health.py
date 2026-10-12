from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200() -> None:
    response = client.get("/health")

    assert response.status_code == 200


def test_health_returns_status_ok() -> None:
    response = client.get("/health")

    assert response.json() == {"status": "ok"}


def test_health_content_type_is_json() -> None:
    response = client.get("/health")

    assert response.headers["content-type"] == "application/json"


def test_health_rejects_post() -> None:
    response = client.post("/health")

    assert response.status_code == 405
