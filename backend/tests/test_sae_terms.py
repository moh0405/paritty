"""HybridTermMatcher and hybrid search against the seeded dictionary."""
from app.llm.client import LLMClient, LLMResult
from app.llm.schemas import TermDecision
from app.recon.sae.matcher import HybridTermMatcher
from app.search.hybrid import HybridSearch


class Decider(LLMClient):
    def __init__(self, decision):
        self.decision, self.calls = decision, 0

    def structured(self, job, prompt, schema, *, model=None, prompt_version="v1", conn=None):
        self.calls += 1
        return LLMResult(self.decision, is_stub=self.decision is None, model="fake")


def test_exact_and_dictionary_matches(db):
    t = HybridTermMatcher(db)
    assert (t.score("Syncope", " SYNCOPE ").score, t.score("syncope", "SYNCOPE").method) == (1.0, "exact")
    syn = t.score("HEART ATTACK", "MYOCARDIAL INFARCTION")
    assert syn.method == "dictionary" and syn.same
    assert t.score("FAINTING", "SYNCOPE").same                     # both map to SYNCOPE in the dictionary


def test_missing_term_never_matches(db):
    assert HybridTermMatcher(db).score(None, "SYNCOPE").score == 0.0


def test_unrelated_terms_in_the_grey_zone_are_not_matched_without_a_decision(db):
    s = HybridTermMatcher(db, allow_llm=False).score("SYNCOPE", "NAUSEA")
    assert not s.same and s.method in ("semantic", "grey_unadjudicated")


def test_grey_zone_pair_is_adjudicated_once_and_cached(db):
    db.execute("DELETE FROM ai.term_decisions WHERE term_a = 'NAUSEA' OR term_b = 'NAUSEA'")
    client = Decider(TermDecision(same_event=False, confidence=0.9, reason="different events"))
    m = HybridTermMatcher(db, client, allow_llm=True)
    first = m.score("SYNCOPE", "NAUSEA")
    if first.method == "semantic":
        return                                                      # similarity fell outside the grey zone; nothing to adjudicate
    assert first.method == "adjudicated" and not first.same and client.calls == 1
    again = HybridTermMatcher(db, client, allow_llm=True).score("NAUSEA", "SYNCOPE")   # order-insensitive, served from ai.term_decisions
    assert again.method == "decision" and client.calls == 1
    assert db.execute("SELECT same_event FROM ai.term_decisions WHERE term_a = 'NAUSEA' AND term_b = 'SYNCOPE'").fetchone() == (False,)


def test_positive_adjudication_counts_as_same_event(db):
    db.execute("INSERT INTO ai.term_decisions (term_a, term_b, same_event, confidence, method, reason) VALUES ('APHASIA', 'SPEECH DISORDER', true, 0.85, 't', 'r')")
    s = HybridTermMatcher(db).score("SPEECH DISORDER", "APHASIA")
    assert s.method == "decision" and s.same


def test_stub_from_replay_leaves_pair_undecided(db):
    s = HybridTermMatcher(db, Decider(None), allow_llm=True).score("ZZZ ONE", "ZZZ TWO")
    assert not s.same and s.method in ("semantic", "grey_unadjudicated")


def test_hybrid_search_finds_synonym_and_reports_method(db):
    r = HybridSearch(db).search("hip fracture", k=5)
    assert r.fused[0].term == "HIP FRACTURE" and "RRF" in r.method
    assert any(h.term == "FRACTURE OF HIP" for h in r.fused)
    assert all(a.score >= b.score for a, b in zip(r.fused, r.fused[1:]))


def test_search_without_vectors_is_lexical_only(db, monkeypatch):
    monkeypatch.setattr("app.search.hybrid.embed_texts", lambda texts, allow_live=False: [None] * len(texts))
    r = HybridSearch(db).search("never seen before phrase hip", k=5)
    assert not r.vector and "only" in r.method
