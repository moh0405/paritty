import pytest

from app.llm.client import LLMClient, LLMResult
from app.llm.schemas import QAAnswer, Quote
from app.protocol.qa_engine import JUDGMENT_CUES, ProtocolQA, sentences, tokens


class Canned(LLMClient):
    def __init__(self, answer):
        self.answer = answer

    def structured(self, job, prompt, schema, *, model=None, prompt_version="v1", conn=None):
        return LLMResult(self.answer, is_stub=self.answer is None, model="fake")


def qa(db, answer=None):
    return ProtocolQA(db, Canned(answer), allow_live_embedding=False)


def test_helpers():
    assert "visit" in tokens("The visit window is") and "the" not in tokens("the visit")
    assert sentences("Intro line\n\nEach scheduled visit has a window of plus or minus 7 days. Short one.\n* A bullet that is long enough to keep.")[:2] == [
        "Each scheduled visit has a window of plus or minus 7 days.", "A bullet that is long enough to keep."]


def test_retrieval_finds_the_relevant_protocol_section(db):
    chunks = qa(db).retrieve("What is the visit window?")
    assert chunks and any("window of plus or minus 7 days" in c["text"] for c in chunks)


def test_extractive_answer_quotes_the_protocol_exactly(db):
    r = qa(db).ask("How fast must we report an SAE?")
    assert r.source == "extractive" and not r.escalate
    assert r.quotes and "within 24 hours" in r.quotes[0]["text"]
    chunk_text = db.execute("SELECT text FROM ai.protocol_chunks WHERE id = %s", (r.quotes[0]["chunk_id"],)).fetchone()[0]
    assert r.quotes[0]["text"] in chunk_text


def test_judgment_and_uncovered_questions_escalate(db):
    for q in ("Should we unblind this subject because of a rash?", "The patient takes ginkgo biloba. Can they stay in the study?",
              "What dose of the study patch should we expect the patient to be on?"):
        assert qa(db).ask(q).escalate, q


def test_judgment_cues_are_specific_to_judgment_phrasing():
    assert JUDGMENT_CUES.search("Is the daughter reliable enough as a caregiver?")
    assert not JUDGMENT_CUES.search("How long do we have to answer a query?")


def test_gemini_answer_is_used_when_its_quote_is_verified(db):
    chunk = qa(db).retrieve("How long do we have to answer a query?")
    real = next(c for c in chunk if "Queries must be answered within 10 days of being sent." in c["text"])
    ans = QAAnswer(answer="Within 10 days.", quotes=[Quote(chunk_id=real["chunk_id"], text="Queries must be answered within 10 days of being sent.")], escalate=False, confidence=0.95)
    r = qa(db, ans).ask("How long do we have to answer a query?")
    assert r.source == "gemini" and not r.escalate and r.quotes[0]["text"].startswith("Queries must")


def test_fabricated_or_misattributed_quotes_force_escalation(db):
    chunks = qa(db).retrieve("How long do we have to answer a query?")
    fake = QAAnswer(answer="Within 30 days.", quotes=[Quote(chunk_id=chunks[0]["chunk_id"], text="Queries must be answered within 30 days.")], escalate=False, confidence=0.99)
    r = qa(db, fake).ask("How long do we have to answer a query?")
    assert r.source == "gemini" and r.escalate and not r.quotes and "no quote could be verified" in r.reason
    wrong_chunk = QAAnswer(answer="x", quotes=[Quote(chunk_id=999999, text="anything")], escalate=False, confidence=0.99)
    assert qa(db, wrong_chunk).ask("How long do we have to answer a query?").escalate


def test_low_confidence_gemini_answer_escalates(db):
    chunks = qa(db).retrieve("visit window")
    t = next(c for c in chunks if "window of plus or minus 7 days" in c["text"])
    low = QAAnswer(answer="Maybe 7 days.", quotes=[Quote(chunk_id=t["chunk_id"], text="Each scheduled visit has a window of plus or minus 7 days around its planned study day.")], escalate=False, confidence=0.4)
    assert qa(db, low).ask("What is the visit window?").escalate
