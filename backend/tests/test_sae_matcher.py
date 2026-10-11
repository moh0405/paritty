from app.recon.sae.matcher import MATCH_THRESHOLD, SaeMatcher, TermScore
from tests.sae_helpers import ae, case, later


class FakeTerms:
    """Term scorer that knows a few pairs; everything else is 'different'."""
    def __init__(self, same=()):
        self.same = {tuple(sorted(p)) for p in same}

    def score(self, a, b):
        if a == b:
            return TermScore(1.0, "exact")
        return TermScore(0.95, "dictionary") if tuple(sorted((a, b))) in self.same else TermScore(0.1, "decision")


def run(aes, cases, same=()):
    return SaeMatcher(FakeTerms(same)).match(aes, cases)


def test_score_formula_and_rejection_threshold():
    m = SaeMatcher(FakeTerms())
    s, _ = m.pair_score(ae(), case())
    assert s == 1.0                                                  # same term, same day
    s, _ = m.pair_score(ae(), case(onset=later(15)))
    assert s == 0.6 + 0.4 * 0.5                                      # 15 days apart: date similarity 0.5
    s, _ = m.pair_score(ae(), case(term="NAUSEA", onset=later(30)))
    assert s == 0.6 * 0.1 and s < MATCH_THRESHOLD                    # different term and a month apart


def test_one_to_one_assignment_prefers_the_best_overall_pairing():
    aes = [ae(id=1, term_coded="SYNCOPE", onset=later(0)), ae(id=2, term_coded="SYNCOPE", onset=later(10))]
    cases = [case(case_id="B", term="SYNCOPE", onset=later(9)), case(case_id="A", term="SYNCOPE", onset=later(1))]
    matches, a_left, c_left = run(aes, cases)
    assert {(m.ae.id, m.case.case_id) for m in matches} == {(1, "A"), (2, "B")} and not a_left and not c_left


def test_synonym_pair_is_matched():
    matches, *_ = run([ae(term_coded="MYOCARDIAL INFARCTION")], [case(term="HEART ATTACK")], same=[("MYOCARDIAL INFARCTION", "HEART ATTACK")])
    assert len(matches) == 1 and matches[0].term.method == "dictionary"


def test_pairs_below_threshold_are_rejected_and_left_unmatched():
    matches, a_left, c_left = run([ae(term_coded="SYNCOPE", onset=later(0))], [case(term="NAUSEA", onset=later(40))])
    assert not matches and len(a_left) == 1 and len(c_left) == 1


def test_matching_is_within_subject_only():
    matches, a_left, c_left = run([ae(usubjid="01-701-1001")], [case(usubjid="01-701-1002")])
    assert not matches and len(a_left) == 1 and len(c_left) == 1


def test_a_case_is_used_at_most_once():
    matches, a_left, _ = run([ae(id=1), ae(id=2)], [case()])
    assert len(matches) == 1 and len(a_left) == 1


def test_unknown_subject_case_stays_unmatched():
    _, _, c_left = run([ae()], [case(usubjid=None)])
    assert len(c_left) == 1
