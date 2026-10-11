import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed.common import connect

client = TestClient(app)


@pytest.fixture
def draft():
    ids = []

    def make(kind="note", state="draft"):
        with connect() as c:
            i = str(c.execute("INSERT INTO ops.drafts (kind, subject_ref, site_id, body, state) VALUES (%s,'01-701-1001','701',%s,%s) RETURNING id",
                              (kind, json.dumps({"text": "x"}), state)).fetchone()[0])
            c.commit()
        ids.append(i)
        return i
    yield make
    with connect() as c:
        c.execute("DELETE FROM ops.issues WHERE links->>'draft_id' = ANY(%s)", (ids,))      # an approved letter or agenda opens issues
        c.execute("DELETE FROM ops.drafts WHERE id = ANY(%s::uuid[])", (ids,))
        c.execute("DELETE FROM audit.log WHERE actor IN ('mm_test','dm_test')")
        c.commit()


def H(role, user):
    return {"X-Role": role, "X-User": user}


def test_only_a_medical_monitor_signs_a_note_and_it_is_audited(draft):
    d = draft("note")
    assert client.post(f"/api/drafts/{d}/sign", headers=H("data_manager", "dm_test")).status_code == 403
    r = client.post(f"/api/drafts/{d}/sign", headers=H("medical_monitor", "mm_test"))
    assert r.status_code == 200 and r.json()["state"] == "signed"
    got = client.get(f"/api/drafts/{d}", headers=H("medical_monitor", "mm_test")).json()
    assert got["state"] == "signed" and got["approved_by"] == "mm_test" and got["approved_at"]
    with connect() as c:
        assert c.execute("SELECT count(*) FROM audit.log WHERE action = 'draft.signed' AND actor = 'mm_test'").fetchone()[0] == 1


def test_a_decided_draft_cannot_be_decided_again(draft):
    d = draft("letter")
    assert client.post(f"/api/drafts/{d}/approve", headers=H("data_manager", "dm_test")).status_code == 200
    assert client.post(f"/api/drafts/{d}/approve", headers=H("data_manager", "dm_test")).status_code == 409
    assert client.post(f"/api/drafts/{d}/reject", json={}, headers=H("data_manager", "dm_test")).status_code in (200, 409)


def test_only_notes_are_signed_and_wrong_roles_are_refused(draft):
    d = draft("letter")
    assert client.post(f"/api/drafts/{d}/sign", headers=H("data_manager", "dm_test")).status_code == 422
    assert client.post(f"/api/drafts/{d}/approve", headers=H("study_lead", "dm_test")).status_code == 403


def test_edit_only_while_a_draft_and_list_filters(draft):
    d = draft("eligibility")
    assert client.patch(f"/api/drafts/{d}", json={"text": "new wording"}, headers=H("data_manager", "dm_test")).status_code == 200
    assert client.get(f"/api/drafts/{d}", headers=H("data_manager", "dm_test")).json()["body"]["text"] == "new wording"
    client.post(f"/api/drafts/{d}/approve", headers=H("data_manager", "dm_test"))
    assert client.patch(f"/api/drafts/{d}", json={"text": "late edit"}, headers=H("data_manager", "dm_test")).status_code == 409
    rows = client.get("/api/drafts?kind=eligibility&state=approved", headers=H("data_manager", "dm_test")).json()
    assert any(r["id"] == d for r in rows)
    assert client.get("/api/drafts/00000000-0000-0000-0000-000000000000", headers=H("data_manager", "dm_test")).status_code == 404
