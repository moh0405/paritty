import json
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.medical.service import MedicalService
from tests.test_library_checks import BAD, lab, subject

D0 = date(2026, 3, 1)
client = TestClient(app)


def add_liver_case(db, u=BAD):
    subject(db, u)
    lab(db, u, "ALT", 170, uln=34, x=5.0, day=D0)
    lab(db, u, "BILI", 3.5, "mg/dL", uln=1.2, x=3.0, day=D0 + timedelta(days=4))
    lab(db, u, "ALP", 100, uln=100, x=1.0, day=D0 + timedelta(days=2))
    db.execute("UPDATE edc.lab SET ctcae_grade = 3 WHERE usubjid = %s AND test_code = 'ALT'", (u,))


def test_inserted_pattern_is_found_ranked_first_and_has_a_verified_finding(db):
    add_liver_case(db)
    svc = MedicalService(db)
    items = svc.review_items(D0 + timedelta(days=10))
    mine = [i for i in items if i.usubjid == BAD]
    assert {i.type for i in mine} >= {"hys_law", "lab_grade3"} and items[0].type == "hys_law"
    assert "requires medical review" in mine[0].title or "Hy's Law" in mine[0].title
    ids = svc.persist_findings(mine, D0 + timedelta(days=10))
    statuses = {s for (s,) in db.execute("SELECT verification_status FROM ai.findings WHERE id = ANY(%s::uuid[])", (list(ids.values()),))}
    assert statuses == {"verified"}
    assert svc.persist_findings(mine, D0 + timedelta(days=11)) == ids                  # idempotent per signal key


def test_profile_and_edish_never_contain_the_treatment_arm(db):
    add_liver_case(db)
    svc = MedicalService(db)
    blob = json.dumps({"profile": svc.profile(BAD), "edish": svc.edish()}, default=str).lower()
    for word in ("placebo", "xanomeline", "\"arm\"", "treatment arm"):
        assert word not in blob
    assert svc.profile("NO-SUCH") is None


def test_profile_has_labs_flags_and_dosing_keys(db):
    add_liver_case(db)
    p = MedicalService(db).profile(BAD)
    assert set(p) >= {"subject", "dosing", "visits", "adverse_events", "conmeds", "labs", "flags", "links"}
    assert [r["x_uln"] for r in p["labs"]["ALT"]] == [5.0]


def test_blinded_api_has_no_arm_and_roles_are_gated():
    r = client.get("/api/medical/edish", headers={"X-Role": "medical_monitor"})
    assert r.status_code == 200 and "arm" not in json.dumps(r.json())
    assert client.get("/api/medical/review-list", headers={"X-Role": "medical_monitor"}).status_code == 200
    assert client.get("/api/medical/review-list", headers={"X-Role": "study_lead"}).status_code == 403
    assert client.get("/api/unblinded/edish", headers={"X-Role": "medical_monitor"}).status_code == 403


def test_unblinding_requires_the_role_a_reason_and_is_audited():
    h = {"X-Role": "unblinded_statistician", "X-User": "test_unblinder"}
    assert client.post("/api/unblind", json={"reason": "x"}, headers={"X-Role": "medical_monitor"}).status_code == 403
    assert client.post("/api/unblind", json={"reason": "x"}, headers=h).status_code == 422
    assert client.get("/api/unblinded/edish", headers=h).status_code == 403             # must unblind first
    assert client.post("/api/unblind", json={"reason": "DSMB request for liver safety review"}, headers=h).status_code == 200
    r = client.get("/api/unblinded/edish", headers=h)
    assert r.status_code == 200 and r.json()["unblinded"] and all("arm" in p for p in r.json()["points"])
    from app.seed.common import connect
    with connect() as c:
        actions = {a for (a,) in c.execute("SELECT action FROM audit.log WHERE actor = 'test_unblinder'")}
        c.execute("DELETE FROM ops.sim_state WHERE key = 'unblind:test_unblinder'")
        c.execute("DELETE FROM audit.log WHERE actor = 'test_unblinder'")
        c.commit()
    assert {"unblind", "unblinded.view"} <= actions
