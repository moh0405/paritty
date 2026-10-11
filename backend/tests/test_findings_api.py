from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
DM = {"X-Role": "data_manager"}


def test_findings_and_stats_endpoints_respond():
    assert client.get("/api/findings", headers=DM).status_code == 200
    s = client.get("/api/findings/stats", headers=DM).json()
    assert {"findings_by_status", "claims_by_status", "grounding_rate", "llm_calls"} <= set(s)


def test_role_without_access_gets_403_not_500():
    assert client.get("/api/findings", headers={"X-Role": "study_lead"}).status_code == 403


def test_unknown_finding_and_citation_are_404():
    assert client.get("/api/findings/00000000-0000-0000-0000-000000000000", headers=DM).status_code == 404
    assert client.get("/api/citations/999999999/source", headers=DM).status_code == 404
