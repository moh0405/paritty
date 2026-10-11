"""The 'Today' list: what waits for a person, by role. Counts only - never patient-level rows."""
import json
from datetime import date

from fastapi.testclient import TestClient

from app import attention
from app.attention import BY_KEY, DECIDE, SOURCES, WATCH, badges, build, count_all
from app.domain.enums import Role
from app.main import app

client = TestClient(app)
DAY = date(2026, 3, 6)


def test_every_source_is_complete_and_points_at_a_page():
    assert len({s.key for s in SOURCES}) == len(SOURCES)
    for s in SOURCES:
        assert s.href.startswith("/") and s.roles and s.kind in (DECIDE, WATCH) and s.help.endswith(".") and s.one != s.many
    text = " ".join(f"{s.one} {s.many} {s.help}" for s in SOURCES).lower()
    assert not any(w in text for w in ("fraud", "misconduct", "diagnos"))


def test_only_what_has_something_waiting_is_listed_and_wording_follows_the_count():
    items = build({"query_drafts": 1, "generated_checks": 3, "notes": 0}, Role.DATA_MANAGER)
    assert [i["title"] for i in items] == ["3 proposed checks to approve or reject", "1 query draft to approve"]
    assert build({}, Role.DATA_MANAGER) == []


def test_own_work_comes_first_then_decisions_before_things_to_watch():
    counts = {"notes": 9, "query_drafts": 2, "lab_open": 50, "generated_checks": 5, "sites_to_contact": 7}
    items = build(counts, Role.DATA_MANAGER)
    assert [(i["key"], i["mine"], i["kind"]) for i in items] == [
        ("generated_checks", True, DECIDE), ("query_drafts", True, DECIDE), ("lab_open", True, WATCH),
        ("notes", False, DECIDE), ("sites_to_contact", False, WATCH)]
    assert [i["key"] for i in build(counts, Role.MEDICAL_MONITOR)][0] == "notes"


def test_badges_count_only_the_callers_own_decisions_per_page():
    items = build({"query_drafts": 2, "query_answers": 3, "critical_queries": 8, "notes": 4}, Role.DATA_MANAGER)
    assert badges(items) == {"/queries": 5}                      # watching is not a decision; notes belong to the medical monitor
    assert badges(build({"notes": 4}, Role.MEDICAL_MONITOR)) == {"/medical": 4}


def test_each_role_has_work_and_the_study_lead_is_never_sent_to_a_patient_level_page():
    for role in (Role.DATA_MANAGER, Role.MEDICAL_MONITOR, Role.CENTRAL_MONITOR, Role.STUDY_LEAD):
        assert any(role in s.roles for s in SOURCES), role
    assert {s.href for s in SOURCES if Role.STUDY_LEAD in s.roles} == {"/agent"}


def test_counts_follow_the_database_and_the_site_scope(db):
    before = count_all(db, DAY)
    assert set(before) == set(BY_KEY)
    for site in ("701", "701", "702"):
        db.execute("INSERT INTO ops.drafts (kind, site_id, body, state) VALUES ('agenda', %s, %s, 'draft')", (site, json.dumps({"text": "x"})))
    db.execute("INSERT INTO ops.drafts (kind, site_id, body, state) VALUES ('letter', '701', %s, 'approved')", (json.dumps({"text": "x"}),))
    db.execute("INSERT INTO ops.issues (site_id, source, title, status, opened) VALUES ('702', 'agenda', 't', 'open', %s), ('702', 'agenda', 'u', 'closed', %s)", (DAY, DAY))
    db.execute("INSERT INTO ops.check_specs (id, type, params, approval_status, source, active) VALUES ('gen_attention_test', 'range', '{}', 'pending_approval', 'generated', false)")
    after = count_all(db, DAY)
    assert after["site_documents"] == before["site_documents"] + 3            # the approved letter no longer waits
    assert after["issues"] == before["issues"] + 1 and after["generated_checks"] == before["generated_checks"] + 1
    scoped, scoped_before = count_all(db, DAY, "701"), count_all(db, DAY, "701,702")
    assert scoped["site_documents"] <= after["site_documents"] - 1 and scoped["issues"] <= after["issues"] - 1
    assert scoped_before["site_documents"] >= scoped["site_documents"] + 1


def test_summary_carries_the_lock_forecast_when_there_is_one(db):
    db.execute("DELETE FROM ops.lock_forecasts")
    assert attention.summary(db, Role.STUDY_LEAD, DAY)["lock"] is None
    db.execute("INSERT INTO ops.lock_forecasts (sim_date, p10, p50, p90, readiness, blockers, n_sims) VALUES (%s, '2027-01-01', '2027-01-10', '2027-02-01', %s, '[]', 100)",
               (DAY, json.dumps({"met": 2, "total": 7})))
    s = attention.summary(db, Role.STUDY_LEAD, DAY)
    assert s["lock"] == {"p10": "2027-01-01", "p50": "2027-01-10", "p90": "2027-02-01", "met": 2, "total": 7}
    assert s["decisions"] == sum(i["count"] for i in s["items"] if i["mine"] and i["kind"] == DECIDE)


def test_api_answers_every_role_with_counts_and_no_patient_identifiers():
    for role in ("data_manager", "medical_monitor", "central_monitor", "study_lead", "unblinded_statistician"):
        r = client.get("/api/attention", headers={"X-Role": role})
        assert r.status_code == 200, role
        body = r.json()
        assert set(body) == {"role", "today", "items", "badges", "decisions", "lock"} and body["role"] == role
        text = json.dumps(body)
        assert "01-7" not in text and "usubjid" not in text and "arm" not in text.replace("alarm", "")       # counts only, blinded
        assert all(set(i) == {"key", "count", "title", "href", "kind", "help", "mine", "roles"} for i in body["items"])
