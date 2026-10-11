"""Milestone 13 against the database: visit plan, agenda/letter drafts (verified), issues, scorecard and the API around them."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.llm.client import LLMResult
from app.llm.schemas import Citation, Claim, VisitAgenda
from app.main import app
from app.seed.common import connect
from app.sites import issues, scorecard_pdf, visit_planner
from app.sites.letters import DISCLAIMER, NothingToRaise, SiteDrafter

client = TestClient(app)
DAY = date(2031, 1, 6)          # later than any simulated day, so these rows are "the latest"
BUSY, CALM = "701", "702"


def H(role, user="m13_test"):
    return {"X-Role": role, "X-User": user}


def plant(conn) -> None:
    """One site with two red indicators and one amber, one site with nothing to raise."""
    for site, kri, value, comp, rag in ((BUSY, "entry_lag_days", 18.0, 3.0, "red"), (BUSY, "query_rate", 4.4, 1.9, "red"),
                                        (BUSY, "sae_rate", 3.1, 2.0, "amber"), (CALM, "entry_lag_days", 3.0, 3.0, "green")):
        conn.execute("INSERT INTO ops.kri_values (sim_date, site_id, kri, value, comparator, rag) VALUES (%s,%s,%s,%s,%s,%s)", (DAY, site, kri, value, comp, rag))
    signals = {"explanations": [{"kind": "anomaly", "name": "terminal_digit", "level": "red", "text": "Blood pressure readings end in 0 or 5 in 61% of 240 readings."}],
               "anomalies": [{"test": "terminal_digit", "flagged": True, "p": 1e-9, "statistic": 80.0, "detail": {}}], "z": {}, "model": None}
    conn.execute("INSERT INTO ops.site_risk (sim_date, site_id, rule_score, model_score, signals) VALUES (%s,%s,80,90,%s), (%s,%s,45,10,%s)",
                 (DAY, BUSY, json.dumps(signals), DAY, CALM, json.dumps({"explanations": [], "anomalies": [], "z": {}, "model": None})))


class Miss:
    """An LLM client with nothing recorded (replay cache miss)."""
    def structured(self, *a, **k):
        return LLMResult(parsed=None, is_stub=True)


class Scripted:
    def __init__(self, parsed):
        self.parsed = parsed

    def structured(self, *a, **k):
        return LLMResult(parsed=self.parsed, model="fake-model")


def lag_claim(text: str) -> Claim:
    ref = f"{DAY}:{BUSY}:entry_lag_days"
    return Claim(text=text, citations=[Citation(table="ops.v_kri", pk=ref, column="value", value="18"), Citation(table="ops.v_kri", pk=ref, column="comparator", value="3")])


def status_of(conn, finding_id: str) -> str:
    return conn.execute("SELECT verification_status FROM ai.findings WHERE id = %s", (finding_id,)).fetchone()[0]


def test_visit_plan_ranks_sites_and_proposes_an_action(db):
    plant(db)
    plan = visit_planner.plan(db, date(2026, 3, 6))
    assert plan["as_of"] == str(DAY) and plan["month"] == "2026-04"
    row = next(s for s in plan["sites"] if s["site_id"] == BUSY)
    assert (row["level"], row["action"], row["reds"], row["ambers"]) == ("red", "visit", 3, 1)      # 2 red KRIs + 1 flagged test
    assert row["priority"] == pytest.approx(0.85 * row["subjects"], abs=0.01) and row["reasons"]
    assert CALM not in {s["site_id"] for s in plan["sites"]}                                        # quiet, no open issues
    priorities = [s["priority"] for s in plan["sites"]]
    assert priorities == sorted(priorities, reverse=True)
    db.execute("INSERT INTO ops.issues (site_id, source, title, status, opened) VALUES (%s,'agenda','x','open',%s)", (CALM, DAY))
    assert next(s for s in visit_planner.plan(db, DAY)["sites"] if s["site_id"] == CALM)["action"] == "remote"


@pytest.mark.parametrize("kind", ["agenda", "letter"])
def test_template_draft_is_verified_cited_and_waits_for_a_person(db, kind):
    plant(db)
    d = SiteDrafter(db, Miss()).draft(BUSY, kind, "cm_test")
    body = d["body"]
    assert d["state"] == "draft" and d["created"] and body["source"] == "template" and body["action"] == "visit"
    assert [i["title"] for i in body["items"]] == ["Review: Median data entry lag (days)", "Review: Queries per 100 data points",
                                                   "Review: Serious adverse events per 100 patient-months", "Review: Blood pressure terminal digits"]
    assert "18.00 days; median across sites 3.00 (red)" in body["text"] and DISCLAIMER in body["text"]
    assert not any(w in body["text"].lower() for w in ("fraud", "misconduct", "fabricat"))
    assert status_of(db, body["finding_id"]) == "verified"                 # every cited KRI cell matched the database
    cited = {r[0] for r in db.execute("SELECT src_table FROM ai.citations WHERE finding_id = %s", (body["finding_id"],))}
    assert "ops.v_kri" in cited
    assert db.execute("SELECT count(*) FROM ops.issues WHERE links->>'draft_id' = %s", (d["id"],)).fetchone()[0] == 0      # nothing happens before approval
    assert db.execute("SELECT count(*) FROM audit.log WHERE action = 'draft.created' AND entity_id = %s", (d["id"],)).fetchone()[0] == 1
    again = SiteDrafter(db, Miss()).draft(BUSY, kind, "cm_test")
    assert again["id"] == d["id"] and not again["created"]                 # one pending draft per site and kind


def test_verified_model_draft_is_used_and_an_unsupported_one_falls_back(db):
    plant(db)
    good = "1. Median data entry lag is 18 days at the site against a median of 3 across sites. These are reasons to look, not conclusions."
    d = SiteDrafter(db, Scripted(VisitAgenda(text=good, claims=[lag_claim("Median data entry lag is 18 days; the median across sites is 3.")]))).draft(BUSY, "agenda", "cm_test")
    assert d["body"]["source"] == "gemini" and d["body"]["text"] == good and status_of(db, d["body"]["finding_id"]) == "verified"
    db.execute("DELETE FROM ops.drafts WHERE id = %s", (d["id"],))
    invented = "Median data entry lag is 42 days at the site."
    d = SiteDrafter(db, Scripted(VisitAgenda(text=invented, claims=[lag_claim(invented)]))).draft(BUSY, "agenda", "cm_test")
    assert d["body"]["source"] == "template" and "42" not in d["body"]["text"]
    statuses = sorted(r[0] for r in db.execute("SELECT verification_status FROM ai.findings WHERE module = 'site_agenda' AND body->>'source' = 'gemini'"))
    assert len(statuses) == 2 and statuses.count("verified") == 1         # the unsupported draft is stored for the record, never shown


def test_site_with_nothing_to_raise_gets_no_draft(db):
    plant(db)
    with pytest.raises(NothingToRaise):
        SiteDrafter(db, Miss()).draft(CALM, "letter", "cm_test")
    with pytest.raises(LookupError):
        SiteDrafter(db, Miss()).draft("NO-SUCH", "letter", "cm_test")


def test_approval_opens_one_issue_per_agenda_item_and_issues_can_be_closed(db):
    plant(db)
    d = SiteDrafter(db, Miss()).draft(BUSY, "agenda", "cm_test")
    made = issues.open_from_draft(db, d["id"], DAY, "cm_test")
    assert len(made) == 4 and issues.open_from_draft(db, d["id"], DAY, "cm_test") == []        # no duplicates while they are open
    rows = [r for r in issues.list_issues(db, site_id=BUSY) if r["links"].get("draft_id") == d["id"]]
    assert len(rows) == 4 and {r["status"] for r in rows} == {"open"} and rows[0]["links"]["draft_id"] == d["id"] and rows[0]["owner"] == "cm_test"
    letter = SiteDrafter(db, Miss()).draft(BUSY, "letter", "cm_test")
    assert len(issues.open_from_draft(db, letter["id"], DAY, "cm_test")) == 1
    closed = issues.update_issue(db, made[0], DAY, "cm_test", status="closed")
    assert closed["status"] == "closed" and closed["closed"] == DAY
    reopened = issues.update_issue(db, made[0], DAY, "cm_test", status="in_progress", owner="dm_test")
    assert reopened["closed"] is None and reopened["owner"] == "dm_test"
    assert issues.update_issue(db, "00000000-0000-0000-0000-000000000000", DAY, "cm_test", status="closed") is None
    with pytest.raises(ValueError):
        issues.update_issue(db, made[0], DAY, "cm_test", status="done")
    assert db.execute("SELECT count(*) FROM audit.log WHERE action IN ('issue.opened','issue.updated') AND actor = 'cm_test'").fetchone()[0] == 7


def test_scorecard_is_a_one_page_pdf():
    site = {"site_id": "701", "name": "Example Clinic", "subjects": 14, "as_of": "2026-06-01", "rule_score": 71.2, "model_score": 88.0,
            "model": {"pattern_label": "late or error-prone data entry"},
            "kri_defs": {"entry_lag_days": {"label": "Median data entry lag (days)", "rule": "red above 14 days, amber above 7", "unit": "days"},
                         "ae_rate": {"label": "Adverse events per patient-month", "rule": "red outside 0.5x-2x of the median site", "unit": "per patient-month"}},
            "kris": {"entry_lag_days": {"value": 18.0, "comparator": 3.0, "rag": "red"}},
            "explanations": [{"text": f"Reason {i} to look."} for i in range(9)],
            "issues": [{"title": "Review: Median data entry lag (days)", "status": "open", "opened": "2026-06-02", "owner": None}]}
    pdf = scorecard_pdf.render(site)
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") + pdf.count(b"/Type /Page>") <= 1
    assert b"/Count 1" in pdf
    assert scorecard_pdf.render({**site, "model_score": None, "model": None, "explanations": [], "issues": []}).startswith(b"%PDF")


# ---- API (its own connection: committed data only) ------------------------------------------------------------
@pytest.fixture
def committed_agenda():
    with connect() as c:
        if not c.execute("SELECT count(*) FROM ops.sim_clock").fetchone()[0]:
            pytest.skip("database not seeded")
        body = {"text": "agenda", "items": [{"title": "Review: m13 test item A", "detail": "a"}, {"title": "Review: m13 test item B", "detail": "b"}], "finding_id": None}
        did = str(c.execute("INSERT INTO ops.drafts (kind, site_id, body, state) VALUES ('agenda', %s, %s, 'draft') RETURNING id", (BUSY, json.dumps(body))).fetchone()[0])
        c.commit()
    yield did
    with connect() as c:
        c.execute("DELETE FROM ops.issues WHERE title LIKE 'Review: m13 test item%'")
        c.execute("DELETE FROM ops.drafts WHERE id = %s", (did,))
        c.execute("DELETE FROM audit.log WHERE actor = 'm13_test'")
        c.commit()


def test_visit_plan_route_is_not_swallowed_by_the_site_route():
    r = client.get("/api/sites/visit-plan?month=2026-09", headers=H("central_monitor"))
    assert r.status_code == 200 and set(r.json()) == {"as_of", "month", "sites"} and r.json()["month"] == "2026-09"


def test_only_monitors_draft_documents_and_work_issues():
    assert client.post(f"/api/sites/{BUSY}/agenda", headers=H("medical_monitor")).status_code == 403
    assert client.post(f"/api/sites/{BUSY}/letter", headers=H("study_lead")).status_code == 403
    assert client.patch("/api/issues/00000000-0000-0000-0000-000000000000", json={"status": "closed"}, headers=H("medical_monitor")).status_code == 403
    assert client.patch("/api/issues/00000000-0000-0000-0000-000000000000", json={"status": "closed"}, headers=H("central_monitor")).status_code == 404
    assert client.patch("/api/issues/00000000-0000-0000-0000-000000000000", json={"status": "done"}, headers=H("central_monitor")).status_code == 422
    assert client.post("/api/sites/NO-SUCH/agenda", headers=H("central_monitor")).status_code == 404


def test_approving_an_agenda_through_the_api_opens_tracked_issues(committed_agenda):
    assert client.get(f"/api/issues?site={BUSY}&status=open", headers=H("central_monitor")).status_code == 200
    r = client.post(f"/api/drafts/{committed_agenda}/approve", headers=H("central_monitor"))
    assert r.status_code == 200 and r.json()["state"] == "approved"
    mine = [i for i in client.get(f"/api/issues?site={BUSY}", headers=H("central_monitor")).json() if i["title"].startswith("Review: m13 test item")]
    assert len(mine) == 2 and {i["status"] for i in mine} == {"open"} and {i["source"] for i in mine} == {"agenda"}
    done = client.patch(f"/api/issues/{mine[0]['id']}", json={"status": "closed"}, headers=H("data_manager"))
    assert done.status_code == 200 and done.json()["status"] == "closed" and done.json()["closed"]
    assert client.get("/api/issues", headers=H("data_manager", "x"), params={"status": "closed", "site": BUSY}).json()
