import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.medical import notes
from app.medical.trends import TESTS, lab_trends
from app.seed.common import connect
from tests.test_library_checks import BAD, subject
from tests.test_medical_service import add_liver_case

client = TestClient(app)
D0 = date(2026, 3, 1)
DAY = D0 + timedelta(days=10)


class NoLlm:
    def structured(self, *a, **k):
        from app.llm.client import LLMResult
        return LLMResult(None, is_stub=True)


def test_note_is_drafted_once_from_verified_claims_and_has_no_arm(db):
    add_liver_case(db)
    d = notes.NoteDrafter(db, NoLlm())
    did = d.draft(BAD, DAY)
    assert did and d.draft(BAD, DAY) == did                         # idempotent: one live note per subject
    body, state, kind = db.execute("SELECT body, state, kind FROM ops.drafts WHERE id = %s", (did,)).fetchone()
    assert (state, kind) == ("draft", "note") and body["source"] == "template" and body["verification_status"] == "verified"
    assert "need medical review" in body["text"] and "5.00x ULN" in body["text"] and body["text"].count("ALT was") == 1
    blob = json.dumps(body).lower()
    assert not any(w in blob for w in ("placebo", "xanomeline", "treatment arm", "fraud", "misconduct"))
    assert db.execute("SELECT verification_status FROM ai.findings WHERE id = %s", (body["finding_id"],)).fetchone()[0] == "verified"


def test_no_flags_means_no_note(db):
    subject(db, BAD)
    assert notes.NoteDrafter(db, NoLlm()).draft(BAD, DAY) is None


def test_a_rejected_note_can_be_redrafted(db):
    add_liver_case(db)
    d = notes.NoteDrafter(db, NoLlm())
    first = d.draft(BAD, DAY)
    db.execute("UPDATE ops.drafts SET state = 'rejected' WHERE id = %s", (first,))
    assert d.draft(BAD, DAY) != first


def test_flagged_subjects_get_notes_and_the_simulator_signs_only_after_waiting(db):
    add_liver_case(db)
    from app.medical.service import MedicalService
    MedicalService(db).run(DAY)
    assert notes.draft_for_flagged(db, DAY, NoLlm()) >= 1
    assert notes.sign_due_notes(db, DAY) == 0                                          # too soon
    assert notes.sign_due_notes(db, DAY + timedelta(days=3)) >= 1
    st, by = db.execute("SELECT state, approved_by FROM ops.drafts WHERE subject_ref = %s", (BAD,)).fetchone()
    assert (st, by) == ("signed", "sim:auto")
    assert db.execute("SELECT count(*) FROM audit.log WHERE action = 'draft.signed' AND actor = 'sim:auto'").fetchone()[0] >= 1


def test_signed_notes_satisfy_the_readiness_criterion(db):
    from app.forecast import readiness
    add_liver_case(db)
    from app.medical.service import MedicalService
    MedicalService(db).run(DAY)
    notes.draft_for_flagged(db, DAY, NoLlm())
    day = db.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
    before = {c["key"]: c for c in readiness.criteria(db, day)}["notes"]["remaining"]
    notes.sign_due_notes(db, DAY + timedelta(days=5))
    after = {c["key"]: c for c in readiness.criteria(db, day)}["notes"]["remaining"]
    assert after < before


def test_trends_validate_inputs_and_return_a_study_series(db):
    out = lab_trends(db, "ALT", "site")
    assert out["series"][0]["key"] == "study" and out["unit"] == "x ULN"
    assert all(p["n"] >= 3 for s in out["series"] for p in s["points"])
    assert [p["planned_day"] for p in out["series"][0]["points"]] == sorted(p["planned_day"] for p in out["series"][0]["points"])
    assert len(lab_trends(db, "ALT", "visit")["series"]) == 1
    with pytest.raises(ValueError):
        lab_trends(db, "NOPE", "site")
    assert "BILI" in TESTS


def test_trend_and_cluster_endpoints():
    h = {"X-Role": "medical_monitor"}
    assert client.get("/api/medical/trends?test=ALT&by=site", headers=h).status_code == 200
    assert client.get("/api/medical/trends?test=XYZ", headers=h).status_code == 422
    c = client.get("/api/medical/clusters", headers=h).json()
    assert set(c) == {"ae_clusters", "alt_creep"}
    assert client.get("/api/medical/clusters", headers={"X-Role": "study_lead"}).status_code == 403


def test_escalation_lifecycle_and_roles():
    mm, dm = {"X-Role": "medical_monitor", "X-User": "esc_mm"}, {"X-Role": "data_manager", "X-User": "esc_dm"}
    assert client.post("/api/medical/escalations", json={"reason": "x"}, headers=mm).status_code == 422
    assert client.post("/api/medical/escalations", json={"reason": "Query about concomitant medication"}, headers={"X-Role": "study_lead"}).status_code == 403
    eid = client.post("/api/medical/escalations", json={"reason": "Possible liver pattern needs a second opinion", "usubjid": "01-701-1001"}, headers=dm).json()["id"]
    try:
        assert any(e["id"] == eid for e in client.get("/api/medical/escalations?status=open", headers=mm).json())
        assert client.patch(f"/api/medical/escalations/{eid}", json={"status": "resolved"}, headers=mm).status_code == 422          # needs a resolution
        assert client.patch(f"/api/medical/escalations/{eid}", json={"status": "resolved", "resolution": "Reviewed; repeat labs ordered"}, headers=dm).status_code == 403
        assert client.patch(f"/api/medical/escalations/{eid}", json={"status": "resolved", "resolution": "Reviewed; repeat labs ordered"}, headers=mm).status_code == 200
        assert not any(e["id"] == eid for e in client.get("/api/medical/escalations?status=open", headers=mm).json())
    finally:
        with connect() as c:
            c.execute("DELETE FROM ops.escalations WHERE id = %s", (eid,))
            c.execute("DELETE FROM audit.log WHERE actor IN ('esc_mm','esc_dm')")
            c.commit()


def test_protocol_ask_saves_a_draft_for_a_person_to_approve():
    r = client.post("/api/protocol/ask", json={"question": "How long do we have to answer a query?"}, headers={"X-Role": "data_manager", "X-User": "ask_dm"})
    assert r.status_code == 200
    out = r.json()
    try:
        assert out["quotes"] and "draft_id" in out
        with connect() as c:
            st, kind = c.execute("SELECT state, kind FROM ops.drafts WHERE id = %s", (out["draft_id"],)).fetchone()
        assert (st, kind) == ("draft", "eligibility")
        assert client.post("/api/protocol/ask", json={"question": "x"}, headers={"X-Role": "study_lead"}).status_code == 403
        hits = client.get("/api/search/protocol?q=liver", headers={"X-Role": "data_manager"}).json()
        assert hits["fused"] and "method" in hits
    finally:
        with connect() as c:
            c.execute("DELETE FROM ops.drafts WHERE id = %s", (out["draft_id"],))
            c.execute("DELETE FROM audit.log WHERE actor = 'ask_dm'")
            c.commit()
