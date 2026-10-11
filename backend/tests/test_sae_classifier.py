"""One test per row of the discrepancy table in spec §9.5."""
from app.recon.sae.classifier import DiscrepancyClassifier
from tests.sae_helpers import DIFF, SAME, ae, case, later, match

clf = DiscrepancyClassifier()


def fields(result):
    return {d.field: d.cls for d in result.discrepancies}


def test_identical_pair_is_clean():
    r = clf.classify_pair(match())
    assert r.overall == "clean" and not r.discrepancies


def test_onset_within_one_day_is_acceptable():
    assert fields(clf.classify_pair(match(c=case(onset=later(1))))) == {"onset": "acceptable"}
    assert fields(clf.classify_pair(match(c=case(onset=later(-1))))) == {"onset": "acceptable"}


def test_onset_more_than_one_day_is_actionable():
    r = clf.classify_pair(match(c=case(onset=later(2))))
    assert fields(r) == {"onset": "actionable"} and r.overall == "actionable"


def test_onset_missing_on_one_side_is_actionable():
    assert fields(clf.classify_pair(match(c=case(onset=None)))) == {"onset": "actionable"}


def test_different_wording_same_coded_term_is_acceptable():
    r = clf.classify_pair(match(c=case(term="FAINTING"), term=SAME))
    assert fields(r) == {"term": "acceptable"} and r.overall == "acceptable"


def test_different_coded_term_is_actionable():
    assert fields(clf.classify_pair(match(c=case(term="NAUSEA"), term=DIFF))) == {"term": "actionable"}


def test_seriousness_differs_is_actionable():
    assert fields(clf.classify_pair(match(c=case(serious="2")))) == {"seriousness": "actionable"}


def test_causality_differs_is_actionable_and_requests_causality_assessment():
    r = clf.classify_pair(match(c=case(causality="Not related")))
    assert fields(r) == {"causality": "actionable"} and r.needs_causality


def test_causality_mapping_probable_possible_remote_none():
    for edc, safety in (("PROBABLE", "Related"), ("POSSIBLE", "Related"), ("REMOTE", "Not related"), ("NONE", "Not related")):
        assert clf.classify_pair(match(a=ae(causality=edc), c=case(causality=safety))).overall == "clean", edc


def test_outcome_differs_with_newer_safety_follow_up_is_acceptable():
    r = clf.classify_pair(match(a=ae(outcome="NOT RECOVERED/NOT RESOLVED"), c=case(outcome="1", version=2, narrative="n Follow-up: resolved.")))
    assert fields(r) == {"outcome": "acceptable", "narrative": "acceptable"} and r.overall == "acceptable"


def test_safety_has_extra_narrative_detail_is_acceptable():
    r = clf.classify_pair(match(c=case(version=2, narrative="n Follow-up: more detail.")))
    assert fields(r) == {"narrative": "acceptable"}


def test_outcome_differs_without_follow_up_is_actionable():
    r = clf.classify_pair(match(a=ae(outcome="NOT RECOVERED/NOT RESOLVED"), c=case(outcome="1")))
    assert fields(r) == {"outcome": "actionable"}


def test_outcome_missing_on_either_side_is_actionable():
    assert fields(clf.classify_pair(match(c=case(outcome=None)))) == {"outcome": "actionable"}
    assert fields(clf.classify_pair(match(a=ae(outcome=None)))) == {"outcome": "actionable"}


def test_death_on_one_side_only_is_critical():
    r = clf.classify_pair(match(c=case(death="1", outcome="5")))
    assert fields(r) == {"death": "critical"} and r.overall == "critical"
    assert fields(clf.classify_pair(match(a=ae(outcome="FATAL")))) == {"death": "critical"}


def test_death_on_both_sides_is_consistent():
    assert clf.classify_pair(match(a=ae(outcome="FATAL"), c=case(death="1", outcome="5"))).overall == "clean"


def test_case_on_one_side_only_is_actionable_and_critical_if_fatal():
    out = clf.classify_unmatched([ae(id=1, entered_at=later(-10)), ae(id=2, outcome="FATAL", entered_at=later(-10))],
                                 [case(case_id="A"), case(case_id="B", death="1")], later(0))
    got = {(o.kind, o.cls) for o in out}
    assert got == {("edc_only", "actionable"), ("edc_only", "critical"), ("safety_only", "actionable"), ("safety_only", "critical")}


def test_recent_unreported_ae_is_pending_not_a_discrepancy():
    out = clf.classify_unmatched([ae(entered_at=later(-1))], [], later(0))
    assert out[0].pending
    assert not clf.classify_unmatched([ae(entered_at=later(-10))], [], later(0))[0].pending
