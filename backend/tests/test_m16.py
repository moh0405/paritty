"""Milestone 16: agent, translation, evaluation summary, exports, NL ask service."""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agent import apply as agent_apply
from app.agent.data_manager import DataManagerAgent, numbers_ok, template_rationale
from app.agent.tools import Candidate
from app.evals.summary import EvalSummarizer
from app.exports import csv as csv_export
from app.exports.signal_pack import build_pack
from app.hub.ask import AskService, Unanswerable
from app.llm.client import LLMClient, LLMResult
from app.llm.schemas import AgentChoice, AgentPlan, Citation, Claim, EvalSummary, SqlProposal, Translation
from app.main import app
from app.queries.translate import LANGUAGES, QueryTranslator, TranslationBlocked, TranslationUnavailable, check, facts
from app.seed.common import connect

client = TestClient(app)
DAY = date(2026, 6, 1)


class Canned(LLMClient):
    def __init__(self, out=None):
        self.out = out

    def structured(self, job, prompt, schema, *, model=None, prompt_version="v1", conn=None):
        v = self.out(prompt) if callable(self.out) else self.out
        return LLMResult(v, is_stub=v is None, model="fake")


# ---- translation ---------------------------------------------------------------------------------------------
SRC = "Subject 01-701-1015: systolic blood pressure of 300 mmHg on 2026-03-04 is outside 60-250. Please verify."


def test_facts_cover_dates_identifiers_and_numbers():
    f = facts(SRC)
    assert {"2026-03-04", "01-701-1015", "300", "60", "250"} <= set(f) and "60-250" not in f
    assert check(SRC, "Sujeto 01-701-1015: 300 mmHg el 2026-03-04, fuera de 60–250.") == []        # an en dash in a range is fine


def test_a_faithful_translation_passes_and_changes_are_caught():
    ok = "Sujeto 01-701-1015: la presión arterial sistólica de 300 mmHg el 2026-03-04 está fuera de 60-250. Por favor verifique."
    assert check(SRC, ok) == []
    assert any("300" in i for i in check(SRC, ok.replace("300", "330")))
    assert any("2026-03-04" in i for i in check(SRC, ok.replace("2026-03-04", "04/03/2026")))
    assert any("01-701-1015" in i for i in check(SRC, ok.replace("01-701-1015", "01-701-1051")))


def test_translator_blocks_bad_output_and_reports_unavailability():
    with pytest.raises(TranslationBlocked):
        QueryTranslator(Canned(Translation(text="Sujeto 01-701-1015: presión de 330 mmHg el 2026-03-04 fuera de 60-250."))).translate(SRC, "Spanish")
    good = Translation(text="Sujeto 01-701-1015: presión de 300 mmHg el 2026-03-04 fuera de 60-250. Verifique.")
    assert QueryTranslator(Canned(good)).translate(SRC, "Spanish").language == "Spanish"
    with pytest.raises(TranslationUnavailable):
        QueryTranslator(Canned(None)).translate(SRC, "Spanish")
    with pytest.raises(ValueError):
        QueryTranslator(Canned(good)).translate(SRC, "Klingon")
    assert "Spanish" in LANGUAGES


def test_translate_endpoint_roles_and_missing_query():
    assert client.post("/api/queries/00000000-0000-0000-0000-000000000000/translate", json={"language": "Spanish"}, headers={"X-Role": "medical_monitor"}).status_code == 403
    assert client.post("/api/queries/00000000-0000-0000-0000-000000000000/translate", json={"language": "Klingon"}, headers={"X-Role": "data_manager"}).status_code == 422
    assert client.post("/api/queries/00000000-0000-0000-0000-000000000000/translate", json={"language": "Spanish"}, headers={"X-Role": "data_manager"}).status_code == 404


# ---- evaluation summary ----------------------------------------------------------------------------------------
@pytest.fixture
def run_with_metrics(db):
    rid = str(db.execute("INSERT INTO eval.scenario_runs (scenario, seed, status) VALUES ('unit', 1, 'done') RETURNING id").fetchone()[0])
    for module, metric, v in (("checks", "recall", 1.0), ("checks", "precision", 0.87), ("sae_recon", "recall", 0.5), ("system", "grounding_rate", 1.0)):
        db.execute("INSERT INTO eval.metrics (scenario_run_id, module, metric, value, detail) VALUES (%s,%s,%s,%s,'{}')", (rid, module, metric, v))
    return rid


def test_template_summary_cites_every_number_and_flags_weak_results(db, run_with_metrics):
    out = EvalSummarizer(db, Canned(None)).summarize(run_with_metrics, DAY)
    assert out["source"] == "template" and out["verification_status"] == "verified"
    assert "0.87" in out["text"] and "Needs attention" in out["text"] and "sae_recon recall is 0.50" in out["text"]


def test_ai_summary_is_used_only_when_verified(db, run_with_metrics):
    ref = f"{run_with_metrics}|checks|recall"
    good = EvalSummary(text="Edit checks found 100% of planted errors.", claims=[Claim(text="Edit checks found 100% of planted errors.", citations=[Citation(table="eval.v_metrics", pk=ref, column="value", value="1.0")])])
    assert EvalSummarizer(db, Canned(good)).summarize(run_with_metrics, DAY)["source"] == "gemini"
    bad = EvalSummary(text="Edit checks found 97% of planted errors.", claims=[Claim(text="Edit checks found 97% of planted errors.", citations=[Citation(table="eval.v_metrics", pk=ref, column="value", value="1.0")])])
    assert EvalSummarizer(db, Canned(bad)).summarize(run_with_metrics, DAY)["source"] == "template"       # 97% is not backed by the cited 1.0


def test_summary_of_an_unknown_run_is_a_key_error(db):
    with pytest.raises(KeyError):
        EvalSummarizer(db, Canned(None)).summarize("00000000-0000-0000-0000-000000000000", DAY)


# ---- agent -----------------------------------------------------------------------------------------------------
def cand(**kw):
    base = dict(id="schedule_call:705", kind="schedule_call", site_id="705", label="Schedule a call with the site", factor=0.7, current_days=10.0, target_days=7.0,
                open_queries=12, est_delta_p50_days=6.0)
    return Candidate(**{**base, **kw})


def test_template_rationale_uses_only_the_simulations_numbers():
    c = cand()
    assert numbers_ok(template_rationale(c), c.numbers())
    assert not numbers_ok("This would save 25 days.", c.numbers())
    assert "If scheduling a call with the site brought" in template_rationale(c)


def test_agent_explanation_is_accepted_only_per_action_when_numbers_match(db):
    c = cand()
    good = AgentPlan(actions=[AgentChoice(candidate_id=c.id, rationale="A call could cut the usual 10 days to about 7, bringing lock about 6 days earlier.")])
    assert DataManagerAgent(db, Canned(good)).explain([c])[c.id][1] == "gemini"
    bad = AgentPlan(actions=[AgentChoice(candidate_id=c.id, rationale="This will bring lock 40 days earlier.")])
    assert DataManagerAgent(db, Canned(bad)).explain([c])[c.id][1] == "template"
    unknown = AgentPlan(actions=[AgentChoice(candidate_id="nope", rationale="x")])
    assert DataManagerAgent(db, Canned(unknown)).explain([c])[c.id][1] == "template"


def test_approved_action_speeds_up_a_site_and_actions_never_undo_each_other(db):
    d1 = str(db.execute("INSERT INTO ops.drafts (kind, site_id, body, state) VALUES ('agent_action','705',%s,'approved') RETURNING id", (json.dumps({"action": "schedule_call", "factor": 0.7}),)).fetchone()[0])
    d2 = str(db.execute("INSERT INTO ops.drafts (kind, site_id, body, state) VALUES ('agent_action','705',%s,'approved') RETURNING id", (json.dumps({"action": "escalate_site", "factor": 0.5}),)).fetchone()[0])
    d3 = str(db.execute("INSERT INTO ops.drafts (kind, site_id, body, state) VALUES ('agent_action','705',%s,'approved') RETURNING id", (json.dumps({"action": "schedule_call", "factor": 0.7}),)).fetchone()[0])
    assert agent_apply.response_factor(db, "705") == 1.0
    agent_apply.apply_action(db, d1, DAY, "t")
    assert agent_apply.response_factor(db, "705") == 0.7
    agent_apply.apply_action(db, d2, DAY, "t")
    assert agent_apply.response_factor(db, "705") == 0.5
    agent_apply.apply_action(db, d3, DAY, "t")
    assert agent_apply.response_factor(db, "705") == 0.5
    assert agent_apply.apply_action(db, "00000000-0000-0000-0000-000000000000", DAY, "t") is None


def test_site_responder_delays_shrink_after_an_approved_action(db):
    from app.sim.site_responder import SiteResponder
    from app.sim.world import WorldModel
    r = SiteResponder(db, WorldModel(), 42)
    qid = "00000000-0000-0000-0000-0000000000aa"
    db.execute("INSERT INTO ops.queries (id, site_id, usubjid, priority, state, text, opened_on) VALUES (%s,'709','u',1,'Sent','t','2026-03-01')", (qid,))
    def due(key):
        db.execute("DELETE FROM ops.site_responses WHERE query_id = %s", (qid,))
        r.schedule(qid, "709", "chk_01", DAY, key)
        return (db.execute("SELECT due_on FROM ops.site_responses WHERE query_id = %s", (qid,)).fetchone()[0] - DAY).days
    slow = [due(k) for k in range(40)]
    db.execute("INSERT INTO ops.sim_state (key, value) VALUES ('response_factor:709', '0.4'::jsonb)")
    fast = [due(k) for k in range(40)]
    assert sum(fast) < sum(slow) and all(f <= s for f, s in zip(fast, slow))


def test_agent_api_roles_and_status():
    assert client.post("/api/agent/plan", headers={"X-Role": "medical_monitor"}).status_code == 403
    assert client.post("/api/agent/enable", json={"enabled": True}, headers={"X-Role": "central_monitor"}).status_code == 403
    assert client.get("/api/agent/status", headers={"X-Role": "data_manager"}).status_code == 200
    assert client.get("/api/agent/actions", headers={"X-Role": "data_manager"}).status_code == 200


# ---- exports -------------------------------------------------------------------------------------------------
def test_csv_exports_have_headers_and_respect_site_scope(db):
    for name in csv_export.SQL:
        text = csv_export.export(db, name, None)
        assert text.splitlines()[0].count(",") >= 5
    scoped = csv_export.export(db, "findings", "no-such-site")
    assert len(scoped.strip().splitlines()) == 1


def test_signal_pack_is_a_blinded_pdf(db):
    pdf = build_pack(db, DAY)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 2000
    import re
    assert not re.search(rb"placebo|xanomeline", pdf, re.I)


def test_export_endpoints():
    h = {"X-Role": "medical_monitor"}
    r = client.get("/api/export/signal-pack.pdf", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:5] == b"%PDF-"
    assert client.get("/api/export/signal-pack.pdf", headers={"X-Role": "study_lead"}).status_code == 403
    assert client.get("/api/export/queries.csv", headers={"X-Role": "data_manager"}).headers["content-type"].startswith("text/csv")
    assert client.get("/api/export/nothing.csv", headers={"X-Role": "data_manager"}).status_code == 404


# ---- natural-language ask --------------------------------------------------------------------------------------
def test_ask_runs_a_valid_proposal_read_only_with_a_row_limit(db):
    out = AskService(db, Canned(SqlProposal(sql="SELECT site_id, open_queries FROM hub.v_open_items ORDER BY open_queries DESC", explanation="Open queries by site."))).ask("Which sites have the most open queries?")
    assert out.source == "gemini" and out.columns == ["site_id", "open_queries"] and "hub.v_open_items" in out.tables and len(out.rows) <= 500


def test_ask_refuses_unsafe_or_unanswerable_proposals(db):
    from app.hub.ask import GuardError
    with pytest.raises(GuardError):
        AskService(db, Canned(SqlProposal(sql="SELECT * FROM unblinded.randomization", explanation="x"))).ask("show the arm")
    with pytest.raises(Unanswerable):
        AskService(db, Canned(SqlProposal(sql="", explanation="The views have no treatment arm.", refuse=True))).ask("who is on placebo?")


def test_ask_without_gemini_uses_the_closest_standard_question_or_says_it_cannot(db):
    out = AskService(db, Canned(None)).ask("Which subjects were dosed after discontinuation?")
    assert out.source == "standard question" and "discontinuation" in out.explanation.lower()
    with pytest.raises(Unanswerable):
        AskService(db, Canned(None)).ask("What is the weather like in Brightwater?")


def test_ask_endpoint_gating():
    r = client.post("/api/hub/ask", json={"question": "Which subjects were dosed after discontinuation?"}, headers={"X-Role": "data_manager"})
    assert r.status_code == 200 and r.json()["source"] in ("gemini", "standard question")
    assert client.post("/api/hub/ask", json={"question": "weather in Brightwater"}, headers={"X-Role": "data_manager"}).status_code == 422
