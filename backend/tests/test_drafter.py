"""Query drafting: verified Gemini draft is used; blocked or missing drafts fall back to the template (spec §9.3, §11)."""
from datetime import date

import pytest

from app.llm.client import LLMClient, LLMResult
from app.llm.schemas import Citation, Claim, QueryDraft
from app.queries.drafter import QueryDrafter
from tests.test_library_checks import BAD, subject, vital


class FakeClient(LLMClient):
    def __init__(self, make):
        self.make, self.prompts = make, []

    def structured(self, job, prompt, schema, *, model=None, prompt_version="v1", conn=None):
        self.prompts.append(prompt)
        draft = self.make(self.prompts[-1])
        return LLMResult(draft, is_stub=draft is None, model="fake")


@pytest.fixture
def failure(db):
    subject(db, BAD)
    vital(db, BAD, "SYSBP", 300)
    pk = str(db.execute("SELECT max(id) FROM edc.vitals WHERE usubjid = %s", (BAD,)).fetchone()[0])
    return dict(check_id="chk_01", usubjid=BAD, site_id="701", src_table="edc.vitals", src_pk=pk,
                observed="300.0", expected="between 60 and 250"), dict(description="Systolic blood pressure outside 60-250 mmHg", severity="major", ctq_category="safety"), pk


def good_draft(pk):
    c = Citation(table="edc.vitals", pk=pk, column="value", value="300")
    return QueryDraft(query_text=f"Systolic BP of 300 for {BAD} is outside 60-250; please verify against the source.", claims=[Claim(text="The recorded value is 300.", citations=[c])])


def test_verified_gemini_draft_is_used(db, failure):
    f, spec, pk = failure
    d = QueryDrafter(db, FakeClient(lambda p: good_draft(pk))).draft(f, spec, date(2026, 3, 6))
    assert d.source == "gemini" and "300" in d.text
    assert db.execute("SELECT verification_status FROM ai.findings WHERE id = %s", (d.finding_id,)).fetchone()[0] == "verified"
    assert db.execute("SELECT count(*) FROM ai.citations WHERE finding_id = %s", (d.finding_id,)).fetchone()[0] >= 2


def test_prompt_contains_evidence_but_never_the_arm(db, failure):
    f, spec, pk = failure
    client = FakeClient(lambda p: good_draft(pk))
    QueryDrafter(db, client).draft(f, spec, date(2026, 3, 6))
    p = client.prompts[0]
    assert '"table": "edc.vitals"' in p and BAD in p and "Placebo" not in p and "Xanomeline" not in p and "unblinded" not in p.lower().replace("never mention", "")


def test_draft_with_invented_number_is_blocked_and_template_is_used(db, failure):
    f, spec, pk = failure
    bad = good_draft(pk)
    bad.query_text = "Systolic BP of 300 appeared 777 times; please verify."
    d = QueryDrafter(db, FakeClient(lambda p: bad)).draft(f, spec, date(2026, 3, 6))
    assert d.source == "template" and "777" not in d.text
    statuses = [s for (s,) in db.execute("SELECT verification_status FROM ai.findings WHERE usubjid = %s ORDER BY created_at", (BAD,))]
    assert statuses == ["partial", "verified"]       # the unusable draft is stored (1 of 2 claims verified); the template finding is attached


def test_draft_citing_a_value_the_row_does_not_have_is_blocked(db, failure):
    f, spec, pk = failure
    bad = good_draft(pk)
    bad.claims[0].citations[0].value = "310"
    assert QueryDrafter(db, FakeClient(lambda p: bad)).draft(f, spec, date(2026, 3, 6)).source == "template"


def test_replay_stub_falls_back_to_template_with_evidence(db, failure):
    f, spec, pk = failure
    d = QueryDrafter(db, FakeClient(lambda p: None)).draft(f, spec, date(2026, 3, 6))
    assert d.source == "template" and BAD in d.text
    fid = d.finding_id
    assert db.execute("SELECT verification_status FROM ai.findings WHERE id = %s", (fid,)).fetchone()[0] == "verified"
    assert db.execute("SELECT src_table, src_column FROM ai.citations WHERE finding_id = %s", (fid,)).fetchone() == ("edc.vitals", "value")


def test_llm_exception_never_breaks_drafting(db, failure):
    f, spec, pk = failure

    class Boom(LLMClient):
        def structured(self, *a, **k):
            raise RuntimeError("quota")
    assert QueryDrafter(db, Boom()).draft(f, spec, date(2026, 3, 6)).source == "template"
