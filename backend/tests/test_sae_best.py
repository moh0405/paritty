import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.evals import causality_eval
from app.llm.client import LLMClient, LLMResult
from app.llm.schemas import CausalityOut, Citation, Claim
from app.main import app
from app.recon.sae import mock_safety_api
from app.recon.sae.causality import CausalityAssessor
from app.recon.sae.e2b_mapper import E2BMapper
from app.recon.sae.reconciler import SaeReconciler
from app.seed.common import connect
from app.sim import safety_desk
from tests.test_library_checks import BAD, exposure, subject
from tests.test_sae_reconciler import TODAY

client = TestClient(app)
DAY = date(2026, 6, 1)
SUBJ = "01-701-9999"


def serious_ae(db, outcome="NOT RECOVERED/NOT RESOLVED", causality="PROBABLE", term="SYNCOPE", onset=date(2026, 5, 1)):
    db.execute("UPDATE ops.sim_clock SET today = %s", (TODAY,))
    db.execute("INSERT INTO edc.subjects (usubjid, site_id, age, sex, consent_at, first_dose_at, status, is_synthetic, entered_at) "
               "VALUES (%s,'701',70,'F','2026-01-01','2026-01-02','enrolled',true,'2026-01-01')", (SUBJ,))
    return db.execute("INSERT INTO edc.ae (usubjid, site_id, source_seq, term_verbatim, term_coded, onset_at, serious, severity, causality, outcome, entered_at) "
                      "VALUES (%s,'701',1,%s,%s,%s,true,'SEVERE',%s,%s,%s) RETURNING id", (SUBJ, term, term, onset, causality, outcome, onset)).fetchone()[0]


def test_mapper_builds_a_complete_message_only_for_serious_aes(db):
    ae = serious_ae(db)
    m = E2BMapper(db).message_for_ae(ae, DAY)
    assert m["subject_ref"] == "SUBJ 9999 / SITE 701" and m["causality"] == "Related" and m["version"] == 1
    p = m["payload"]
    assert p["serious"] == "1" and p["patient"]["reaction"][0]["reactionmeddrapt"] == "SYNCOPE" and p["patient"]["reaction"][0]["reactionstartdate"] == "20260501"
    assert mock_safety_api.validate(m) == []
    db.execute("UPDATE edc.ae SET serious = false WHERE id = %s", (ae,))
    assert E2BMapper(db).message_for_ae(ae, DAY) is None and E2BMapper(db).message_for_ae(-1, DAY) is None


def test_validation_names_what_is_wrong():
    assert any("subject_ref" in e for e in mock_safety_api.validate({"payload": {}}))
    bad = {"subject_ref": "x", "payload": {"safetyreportid": "R", "receivedate": "20260101", "serious": "9", "patient": {"reaction": [{"reactionstartdate": "2026-01-01"}]}}}
    errs = " ".join(mock_safety_api.validate(bad))
    assert "reactionmeddrapt" in errs and "serious must be" in errs and "YYYYMMDD" in errs


def test_inbox_message_is_a_safety_case_and_duplicates_are_rejected(db):
    ae = serious_ae(db)
    msg = E2BMapper(db).message_for_ae(ae, DAY)
    ack = mock_safety_api.submit(db, msg, ae, DAY)
    assert ack["status"] == "received"
    row = db.execute("SELECT id, version, reaction_term, onset, subject_ref, available_on FROM safety.v_cases WHERE safetyreportid = %s", (msg["payload"]["safetyreportid"],)).fetchone()
    assert row[0] >= 1_000_000_000 and row[1:4] == (1, "SYNCOPE", date(2026, 5, 1)) and str(row[5]) == str(DAY)
    again = mock_safety_api.submit(db, msg, ae, DAY)
    assert again["status"] == "rejected" and "already exists" in again["errors"][0]
    assert db.execute("SELECT count(*) FROM mock_safety.inbox WHERE status = 'rejected'").fetchone()[0] >= 1
    assert mock_safety_api.latest_version(db, msg["payload"]["safetyreportid"]) == 1


def test_missing_case_is_opened_through_the_inbox_and_reconciles_clean(db):
    ae = serious_ae(db, outcome="RECOVERED/RESOLVED")
    rec = SaeReconciler(db)
    rec.run(TODAY, allow_llm=False)
    assert ("chk_22", False) in {(c, r) for c, r in db.execute("SELECT check_id, resolved_on IS NOT NULL FROM ops.check_failures WHERE usubjid = %s", (SUBJ,))}
    assert safety_desk.open_case(db, ae, TODAY)
    assert not safety_desk.open_case(db, ae, TODAY)                                  # a second attempt does nothing
    rec.run(TODAY, allow_llm=False)
    assert ("chk_22", True) in {(c, r) for c, r in db.execute("SELECT check_id, resolved_on IS NOT NULL FROM ops.check_failures WHERE usubjid = %s", (SUBJ,))}
    assert db.execute("SELECT count(*) FROM mock_safety.inbox WHERE source_ae_id = %s AND status = 'received'", (ae,)).fetchone()[0] == 1


def test_follow_up_for_an_inbox_case_appends_a_new_inbox_version(db):
    ae = serious_ae(db, outcome="RECOVERED/RESOLVED")
    safety_desk.open_case(db, ae, TODAY)
    cid = E2BMapper.report_id(ae)
    db.execute("UPDATE edc.ae SET onset_at = onset_at + 5 WHERE id = %s", (ae,))
    row = dict(zip(("term_coded", "onset_at", "serious", "causality", "outcome"), db.execute("SELECT term_coded, onset_at, serious, causality, outcome FROM edc.ae WHERE id = %s", (ae,)).fetchone()))
    assert safety_desk.issue_followup(db, cid, row, "onset", TODAY)
    versions = [v for (v,) in db.execute("SELECT version FROM safety.v_cases WHERE safetyreportid = %s ORDER BY version", (cid,))]
    assert versions == [1, 2] and db.execute("SELECT count(*) FROM safety.case_versions WHERE safetyreportid = %s", (cid,)).fetchone()[0] == 0
    assert db.execute("SELECT onset FROM safety.v_cases WHERE safetyreportid = %s AND version = 2", (cid,)).fetchone()[0] == date(2026, 5, 6)


# ---- causality ---------------------------------------------------------------------------------------------------
class Canned(LLMClient):
    def __init__(self, out):
        self.out, self.prompts = out, []

    def structured(self, job, prompt, schema, *, model=None, prompt_version="v1", conn=None):
        self.prompts.append(prompt)
        return LLMResult(self.out(prompt) if callable(self.out) else self.out, is_stub=self.out is None, model="fake")


def case_with_history(db):
    ae = serious_ae(db)
    exposure(db, SUBJ, date(2026, 1, 2), date(2026, 4, 20))
    db.execute("INSERT INTO edc.conmeds (usubjid, site_id, term, start_at, entered_at) VALUES (%s,'701','ASPIRIN',%s,%s)", (SUBJ, date(2026, 4, 28), date(2026, 4, 28)))
    safety_desk.open_case(db, ae, TODAY)
    return E2BMapper.report_id(ae), ae


def good_output(db, cid, confidence=0.9, category="possible"):
    first = db.execute("SELECT first_dose_at FROM edc.subjects WHERE usubjid = %s", (SUBJ,)).fetchone()[0]
    sid = SUBJ
    return CausalityOut(category=category, confidence=confidence, alternative_causes=["aspirin started shortly before onset"], escalate=False,
                        evidence=[Claim(text=f"The subject's first dose was on {first}.", citations=[Citation(table="edc.subjects", pk=sid, column="first_dose_at", value=str(first))])])


def test_verified_confident_assessment_is_not_escalated_and_prompt_is_arm_free(db):
    cid, _ = case_with_history(db)
    c = Canned(lambda p: good_output(db, cid))
    out = CausalityAssessor(db, c).assess(cid, DAY)
    assert (out["category"], out["escalate"], out["verification_status"], out["source"]) == ("possible", False, "verified", "gemini")
    p = c.prompts[0]
    assert '"table": "edc.exposure"' in p and "ASPIRIN" in p and "narrative" not in p.lower().replace("free-text narrative", "") and "placebo" not in p.lower() and "xanomeline" not in p.lower()
    stored = db.execute("SELECT category, escalate FROM ai.causality_assessments WHERE case_id = %s", (cid,)).fetchone()
    assert stored == ("possible", False)


@pytest.mark.parametrize("confidence,why", [(0.4, "below")])
def test_low_confidence_escalates(db, confidence, why):
    cid, _ = case_with_history(db)
    out = CausalityAssessor(db, Canned(lambda p: good_output(db, cid, confidence))).assess(cid, DAY)
    assert out["escalate"] and any(why in w for w in out["why"])


def test_fabricated_evidence_is_blocked_and_escalated(db):
    cid, _ = case_with_history(db)
    bad = CausalityOut(category="probable", confidence=0.95, alternative_causes=[], escalate=False,
                       evidence=[Claim(text="The subject's first dose was on 1999-01-01.", citations=[Citation(table="edc.subjects", pk=SUBJ, column="first_dose_at", value="1999-01-01")])])
    out = CausalityAssessor(db, Canned(bad)).assess(cid, DAY)
    assert out["verification_status"] == "blocked" and out["escalate"] and any("verification" in w for w in out["why"])


def test_without_gemini_the_result_is_a_verified_worksheet_that_escalates(db):
    cid, _ = case_with_history(db)
    out = CausalityAssessor(db, Canned(None)).assess(cid, DAY)
    assert out["category"] == "unassessable" and out["source"] == "worksheet" and out["escalate"] and out["verification_status"] == "verified"
    texts = db.execute("SELECT body->'claims' FROM ai.findings WHERE id = %s", (out["finding_id"],)).fetchone()[0]
    assert any("first dose" in t["text"] for t in texts) and any("aspirin" in t["text"].lower() for t in texts)


def test_unknown_or_unlinkable_case_returns_none(db):
    assert CausalityAssessor(db, Canned(None)).assess("NO-SUCH-CASE", DAY) is None


def test_conflicts_are_assessed_once_each(db):
    cid, _ = case_with_history(db)
    a = CausalityAssessor(db, Canned(None))
    assert a.assess_conflicts(DAY, [cid, cid]) == 1 and a.assess_conflicts(DAY, [cid]) == 0


def test_agreement_and_kappa_against_the_reference(db):
    for i, (ref, got) in enumerate([("possible", "possible"), ("probable", "probable"), ("unlikely", "possible"), ("possible", "possible")]):
        db.execute("INSERT INTO answer_key.causality_reference (case_id, category, rule_trace) VALUES (%s,%s,'{}')", (f"K{i}", ref))
        db.execute("INSERT INTO ai.causality_assessments (case_id, usubjid, category, confidence, escalate, body, verification_status) VALUES (%s,'u',%s,0.9,false,%s,'verified')",
                   (f"K{i}", got, json.dumps({"source": "gemini"})))
    r = causality_eval.score(db, db, DAY, sample=0)
    assert r["ai_assessed"] == 4 and r["agreement"] == 0.75 and 0 < r["kappa"] < 1


# ---- API -------------------------------------------------------------------------------------------------------
def test_mock_safety_api_roles_and_flow():
    dm = {"X-Role": "data_manager", "X-User": "ms_dm"}
    msg = {"subject_ref": "SUBJ 7777 / SITE 701", "version": 1, "causality": "Related", "payload": {"safetyreportid": "LSAPITEST1", "receivedate": "20260301", "serious": "1",
           "patient": {"reaction": [{"reactionmeddrapt": "FALL", "reactionstartdate": "20260228", "reactionoutcome": "1"}]}}}
    try:
        assert client.post("/api/mock-safety/cases", json={"message": msg}, headers={"X-Role": "medical_monitor"}).status_code == 403
        ack = client.post("/api/mock-safety/cases", json={"message": msg}, headers=dm).json()
        assert ack["status"] == "received" and client.post("/api/mock-safety/cases", json={"message": msg}, headers=dm).json()["status"] == "rejected"
        assert client.get(f"/api/mock-safety/cases/{ack['id']}", headers=dm).json()["message"]["payload"]["safetyreportid"] == "LSAPITEST1"
        assert any(r["safetyreportid"] == "LSAPITEST1" for r in client.get("/api/mock-safety/cases", headers=dm).json())
        assert client.get("/api/mock-safety/cases/999999999", headers=dm).status_code == 404
        assert client.post("/api/mock-safety/submit/999999999", headers=dm).status_code == 404
    finally:
        with connect() as c:
            c.execute("DELETE FROM mock_safety.inbox WHERE message->'payload'->>'safetyreportid' = 'LSAPITEST1'")
            c.execute("DELETE FROM audit.log WHERE actor = 'ms_dm'")
            c.commit()


def test_causality_endpoints_enforce_roles_and_handle_unknown_cases():
    assert client.post("/api/recon/sae/cases/X/causality", headers={"X-Role": "central_monitor"}).status_code == 403
    assert client.post("/api/recon/sae/cases/NO-SUCH/causality", headers={"X-Role": "medical_monitor"}).status_code == 404
    assert client.get("/api/causality", headers={"X-Role": "medical_monitor"}).status_code == 200
    assert client.get("/api/causality/00000000-0000-0000-0000-000000000000", headers={"X-Role": "medical_monitor"}).status_code == 404
