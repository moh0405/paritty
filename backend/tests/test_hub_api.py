from fastapi.testclient import TestClient

from app.main import app
from app.seed.common import connect

client = TestClient(app)
DM = {"X-Role": "data_manager", "X-User": "hub_test"}


def test_catalog_dq_and_questions_endpoints():
    assert client.get("/api/hub/catalog?q=lab", headers=DM).status_code == 200
    dq = client.get("/api/hub/dq", headers=DM).json()
    assert dq["dimensions"] == ["completeness", "validity", "consistency", "timeliness"]
    assert [q["id"] for q in client.get("/api/hub/questions").json()] == [1, 2, 3, 4, 5]
    assert client.get("/api/hub/questions/2", headers=DM).json()["level"] == "patient-level"
    assert client.get("/api/hub/questions/2", headers={"X-Role": "study_lead"}).json()["level"] == "site-level"
    assert client.get("/api/hub/questions/99", headers=DM).status_code == 404


def test_lineage_rejects_unknown_entities():
    assert client.get("/api/lineage/nonsense/1", headers=DM).status_code == 404
    assert client.get("/api/lineage/finding/00000000-0000-0000-0000-000000000000", headers=DM).json()["steps"] == []


def test_review_flow_handles_source_ids_with_slashes_and_enforces_roles():
    sid = "SUBJ 9991 / SITE 701"
    with connect() as c:
        c.execute("DELETE FROM hub.subject_xwalk WHERE source_id = %s", (sid,))
        c.execute("INSERT INTO hub.subject_xwalk (canonical_subject, system, source_id, confidence, method, status) VALUES (NULL,'safety',%s,0.5,'fuzzy','unmatched')", (sid,))
        sub = c.execute("SELECT usubjid FROM edc.subjects LIMIT 1").fetchone()[0]
        c.commit()
    try:
        url = f"/api/hub/xwalk/safety/{sid}"
        assert client.post(url + "/confirm", json={}, headers={"X-Role": "medical_monitor"}).status_code == 403
        assert client.post(url + "/confirm", json={}, headers=DM).status_code == 422                       # unmatched: a person must say which subject
        assert client.post(url + "/confirm", json={"canonical": "01-000-0000"}, headers=DM).status_code == 422   # and it must exist
        ok = client.post(url + "/confirm", json={"canonical": sub}, headers=DM)
        assert ok.status_code == 200 and ok.json()["status"] == "confirmed"
        with connect() as c:
            assert c.execute("SELECT canonical_subject, status, confirmed_by, method FROM hub.subject_xwalk WHERE source_id = %s", (sid,)).fetchone() == (sub, "confirmed", "hub_test", "manual")
            assert c.execute("SELECT count(*) FROM audit.log WHERE action = 'xwalk.confirmed' AND actor = 'hub_test'").fetchone()[0] >= 1
        assert client.post(url + "/reject", headers=DM).status_code == 200
        assert client.post("/api/hub/xwalk/safety/NOPE/confirm", json={}, headers=DM).status_code == 404
    finally:
        with connect() as c:
            c.execute("DELETE FROM hub.subject_xwalk WHERE source_id = %s", (sid,))
            c.execute("DELETE FROM audit.log WHERE actor = 'hub_test'")
            c.commit()


def test_study_lead_can_use_catalog_and_dq_but_not_review_mappings():
    lead = {"X-Role": "study_lead"}
    assert client.get("/api/hub/catalog", headers=lead).status_code == 200
    assert client.get("/api/hub/dq", headers=lead).status_code == 200
    assert client.get("/api/hub/xwalk", headers=lead).status_code == 200
    assert client.post("/api/hub/xwalk/safety/x/confirm", json={}, headers=lead).status_code == 403
