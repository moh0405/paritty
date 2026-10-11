import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.checks.generator import CheckGenerator, extract_rules
from app.llm.client import LLMClient, LLMResult
from app.llm.schemas import CheckSpecProposal, ProposedCheck
from app.main import app
from app.protocol.chunker import chunk_protocol
from app.seed.common import PROTOCOL
from app.sim.daily_cycle import DailyCycle
from app.sim.reset import reset

client = TestClient(app)


def protocol_chunks():
    return chunk_protocol((PROTOCOL / "protocol.md").read_text())


def test_rule_extractor_finds_the_numeric_limits_with_exact_quotes():
    found = [p for i, c in enumerate(protocol_chunks()) for p in extract_rules(i, c.text)]
    assert {p.id_suffix for p in found} == {"age", "screening_sbp", "screening_alt", "screening_bili"}
    texts = {i: c.text for i, c in enumerate(protocol_chunks())}
    for p in found:
        assert p.quote in texts[p.chunk_id] and p.quote.endswith(".")
        spec = json.loads(p.params_json)
        assert spec["table"] in ("edc.subjects", "edc.vitals", "edc.lab")
    sbp = next(p for p in found if p.id_suffix == "screening_sbp")
    assert json.loads(sbp.params_json)["max"] == pytest.approx(159.99) and "160 mmHg" in sbp.quote


class FakeProposer(LLMClient):
    def __init__(self, checks):
        self.checks = checks

    def structured(self, job, prompt, schema, *, model=None, prompt_version="v1", conn=None):
        return LLMResult(CheckSpecProposal(checks=self.checks) if self.checks is not None else None, is_stub=self.checks is None, model="fake")


def load_chunks(db):
    db.execute("DELETE FROM ai.protocol_chunks")
    for c in protocol_chunks():
        db.execute("INSERT INTO ai.protocol_chunks (section, text, is_synthetic) VALUES (%s,%s,%s)", (c.section, c.text, c.is_synthetic))
    return db.execute("SELECT id, text FROM ai.protocol_chunks ORDER BY id").fetchall()


def good_proposal(chunk_id, text):
    quote = "Seated systolic blood pressure at Screening 1 must be below 160 mmHg."
    assert quote in text
    return ProposedCheck(id_suffix="llm_sbp", type="range", params_json=json.dumps({"table": "edc.vitals", "column": "value", "test_code": "SYSBP", "visit": "SCREENING 1", "max": 159.99}),
                         description="Screening systolic BP not below 160", ctq_category="eligibility", severity="critical", quote=quote, chunk_id=chunk_id)


def test_generation_without_llm_creates_pending_checks_with_dry_run_counts(db):
    load_chunks(db)
    out = CheckGenerator(db, FakeProposer(None)).generate(use_llm=True)
    ok = [g for g in out if g.status == "pending_approval"]
    assert len(ok) == 4 and all(g.source == "rule_extractor" and g.dry_run_count is not None for g in ok)
    row = db.execute("SELECT approval_status, rationale->>'quote', source FROM ops.check_specs WHERE id = 'gen_age'").fetchone()
    assert row[0] == "pending_approval" and row[1].startswith("Subjects must be between") and row[2] == "generated"
    assert CheckGenerator(db, FakeProposer(None)).generate()[0].reason == "already proposed"


def test_pending_checks_do_not_run_until_approved(db):
    from app.checks.runner import load_specs
    load_chunks(db)
    CheckGenerator(db, FakeProposer(None)).generate()
    assert not [s for s in load_specs(db) if s.id.startswith("gen_")]
    db.execute("UPDATE ops.check_specs SET approval_status = 'approved' WHERE id = 'gen_age'")
    assert [s.id for s in load_specs(db) if s.id.startswith("gen_")] == ["gen_age"]


def test_validation_rejects_bad_quotes_unsupported_types_and_unknown_columns(db):
    chunks = load_chunks(db)
    cid, text = next((i, t) for i, t in chunks if "Seated systolic" in t)
    bad_quote = good_proposal(cid, text).model_copy(update={"id_suffix": "bad_quote", "quote": "Systolic pressure must stay low."})
    bad_type = good_proposal(cid, text).model_copy(update={"id_suffix": "bad_type", "type": "external_lab"})
    bad_col = good_proposal(cid, text).model_copy(update={"id_suffix": "bad_col", "params_json": json.dumps({"table": "edc.vitals", "column": "value; DROP TABLE edc.ae", "min": 1})})
    bad_chunk = good_proposal(cid, text).model_copy(update={"id_suffix": "bad_chunk", "chunk_id": 999999})
    good = good_proposal(cid, text)
    out = {g.id: g for g in CheckGenerator(db, FakeProposer([bad_quote, bad_type, bad_col, bad_chunk, good])).generate()}
    assert [k for k, g in out.items() if g.status == "pending_approval"] == ["gen_llm_sbp"] and out["gen_llm_sbp"].source == "gemini"
    assert "quoted sentence" in out["gen_bad_quote"].reason and "not supported" in out["gen_bad_type"].reason
    assert "invalid" in out["gen_bad_col"].reason and "quoted sentence" in out["gen_bad_chunk"].reason
    assert db.execute("SELECT count(*) FROM ops.check_specs WHERE id LIKE 'gen_bad%'").fetchone()[0] == 0     # rejected proposals are never stored


def test_approved_generated_check_fires_on_the_next_cycle(db):
    reset(db)
    DailyCycle(db).run()
    load_chunks(db)
    CheckGenerator(db, FakeProposer(None)).generate()
    db.execute("UPDATE edc.vitals SET value = 175 WHERE id = (SELECT id FROM edc.vitals WHERE test_code = 'SYSBP' AND visit = 'SCREENING 1' LIMIT 1)")
    assert db.execute("SELECT count(*) FROM ops.check_failures WHERE check_id = 'gen_screening_sbp'").fetchone()[0] == 0
    db.execute("UPDATE ops.check_specs SET approval_status = 'approved', approved_by = 'test' WHERE id = 'gen_screening_sbp'")
    DailyCycle(db).run()
    assert db.execute("SELECT count(*) FROM ops.check_failures WHERE check_id = 'gen_screening_sbp'").fetchone()[0] >= 1


def test_only_a_data_manager_can_decide_and_decisions_are_audited():
    assert client.post("/api/checks/generate", json={"use_llm": False}, headers={"X-Role": "medical_monitor"}).status_code == 403
    assert client.post("/api/checks/gen_nothing/approve", headers={"X-Role": "central_monitor"}).status_code == 403
    assert client.post("/api/checks/gen_nothing/approve", headers={"X-Role": "data_manager"}).status_code == 404
    assert isinstance(client.get("/api/checks/effectiveness", headers={"X-Role": "data_manager"}).json(), list)
