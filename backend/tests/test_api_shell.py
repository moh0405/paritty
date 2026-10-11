from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_me_defaults_to_data_manager():
    assert client.get("/api/me").json()["role"] == "data_manager"


def test_me_rejects_unknown_role():
    assert client.get("/api/me", headers={"X-Role": "root"}).status_code == 400


def test_health_degrades_without_db():
    assert client.get("/api/health").json()["status"] in {"ok", "degraded"}
