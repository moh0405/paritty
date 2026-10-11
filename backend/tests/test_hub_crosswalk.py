from datetime import date

import pytest

from app.hub.adapters import ADAPTERS
from app.hub.crosswalk import CrosswalkBuilder, SubjectMap
from app.llm.client import LLMClient, LLMResult
from app.llm.schemas import XwalkDecision


class Pick(LLMClient):
    def __init__(self, decision):
        self.decision, self.calls = decision, 0

    def structured(self, job, prompt, schema, *, model=None, prompt_version="v1", conn=None):
        self.calls += 1
        return LLMResult(self.decision, is_stub=self.decision is None, model="fake")


def builder(allow_llm=False, client=None):
    b = CrosswalkBuilder.__new__(CrosswalkBuilder)
    b.conn, b.client, b.allow_llm = None, client, allow_llm
    b.subjects = {"701": ["01-701-1015", "01-701-1023", "01-701-2015"], "702": ["01-702-1100"]}
    b.sites = {"701": "Halvren Memory Clinic", "702": "Ostrava Brook Neurology"}
    return b


def test_exact_normalized_match():
    r = builder().resolve_subject(ADAPTERS["lab_vendor"], "PT701-1015")
    assert (r.canonical, r.confidence, r.method) == ("01-701-1015", 1.0, "normalized")


def test_repaired_lookalike_characters_lower_confidence_a_little():
    r = builder().resolve_subject(ADAPTERS["lab_vendor"], "PT701-1O15")
    assert r.canonical == "01-701-1015" and r.method == "repaired" and 0.9 < r.confidence < 1.0


def test_irt_last_three_digits_resolve_when_unique_at_the_site():
    r = builder().resolve_subject(ADAPTERS["irt"], "R-701-023")
    assert r.canonical == "01-701-1023" and r.method == "normalized"


def test_irt_ambiguous_tail_goes_to_a_person():
    r = builder().resolve_subject(ADAPTERS["irt"], "R-701-015")          # 1015 and 2015 both end in 015
    assert r.canonical is None and r.status == "unmatched"


def test_ambiguous_tail_can_be_adjudicated():
    r = builder(True, Pick(XwalkDecision(chosen="01-701-1015", confidence=0.9, reason="kit dates match"))).resolve_subject(ADAPTERS["irt"], "R-701-015")
    assert r.canonical == "01-701-1015" and r.method == "adjudicated"


def test_missing_separator_is_handled_by_the_fuzzy_matcher():
    r = builder().resolve_subject(ADAPTERS["lab_vendor"], "PT7011015")
    assert r.canonical == "01-701-1015" and r.method == "fuzzy" and r.confidence >= 0.92


def test_swapped_digits_are_not_auto_matched():
    r = builder().resolve_subject(ADAPTERS["lab_vendor"], "PT701-1051")
    assert r.canonical is None and r.status == "unmatched"


def test_unknown_subject_is_unmatched_for_a_person():
    r = builder().resolve_subject(ADAPTERS["lab_vendor"], "PT799-9999")
    assert r.canonical is None and r.status == "unmatched"


def test_adjudication_must_choose_a_listed_candidate():
    r = builder(True, Pick(XwalkDecision(chosen="01-999-0000", confidence=0.99, reason="invented"))).resolve_subject(ADAPTERS["lab_vendor"], "PT701-1051")
    assert r.canonical is None


def test_site_codes_names_and_duplicates():
    b = builder()
    assert b.resolve_site("SITE-0701", "x").canonical == "701"
    dup = b.resolve_site("SITE-0701B", "x")
    assert dup.canonical == "701" and dup.method == "duplicate_record" and dup.confidence == 0.9
    assert b.resolve_site("SITE-0750", "Zephyr Ridge Research").canonical is None          # a real site that is not in the EDC
    by_name = b.resolve_site("CLINIC-X", "The Halvren Memory Clinic, LLC")
    assert by_name.canonical == "701" and by_name.method == "fuzzy"


def test_subject_map_uses_rows_then_falls_back_to_parsing(db):
    db.execute("INSERT INTO hub.subject_xwalk (canonical_subject, system, source_id, confidence, method, status) VALUES ('01-701-1015','lab_vendor','PT-WEIRD',0.9,'fuzzy','proposed')")
    db.execute("INSERT INTO hub.subject_xwalk (canonical_subject, system, source_id, confidence, method, status) VALUES ('01-701-1023','lab_vendor','PT701-1023',1,'normalized','rejected')")
    db.execute("INSERT INTO hub.subject_xwalk (canonical_subject, system, source_id, confidence, method, status) VALUES (NULL,'lab_vendor','PT799-0001',0.4,'fuzzy','unmatched')")
    m = SubjectMap(db)
    assert m.get("lab_vendor", "PT-WEIRD") == "01-701-1015"          # row wins
    assert m.get("lab_vendor", "PT701-1023") is None                 # a rejected mapping is not used, and not re-guessed
    assert m.get("lab_vendor", "PT799-0001") is None                 # seen, unmatched: no guessing
    assert m.get("lab_vendor", "PT701-1999") == "01-701-1999"        # never seen: strict parse
    assert m.get("safety", "SUBJ 1015 / SITE 701") == "01-701-1015"


def test_build_maps_new_identifiers_and_keeps_confirmed_rows(db):
    db.execute("DELETE FROM hub.subject_xwalk")
    db.execute("DELETE FROM hub.site_xwalk")
    day = db.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
    b = CrosswalkBuilder(db)
    first = b.build(day)
    n = db.execute("SELECT count(*) FROM hub.subject_xwalk").fetchone()[0]
    assert n > 0 and db.execute("SELECT count(*) FROM hub.site_xwalk WHERE system = 'ctms'").fetchone()[0] == 26
    sid = db.execute("SELECT source_id FROM hub.subject_xwalk WHERE status = 'proposed' LIMIT 1").fetchone()[0]
    db.execute("UPDATE hub.subject_xwalk SET status = 'confirmed', confirmed_by = 'dm' WHERE source_id = %s", (sid,))
    second = b.build(day)
    assert second["new"] == 0 and db.execute("SELECT status FROM hub.subject_xwalk WHERE source_id = %s", (sid,)).fetchone()[0] == "confirmed"
    assert db.execute("SELECT canonical_site FROM hub.site_xwalk WHERE source_id = 'SITE-0750'").fetchone()[0] is None
