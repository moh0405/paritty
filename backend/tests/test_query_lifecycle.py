from datetime import date

import pytest

from app.queries import lifecycle as lc
from app.queries.prioritizer import age_weight, priority

LEGAL = [
    (lc.DRAFT, "approve", lc.APPROVED), (lc.DRAFT, "close", lc.CLOSED), (lc.APPROVED, "send", lc.SENT), (lc.APPROVED, "close", lc.CLOSED),
    (lc.SENT, "answer", lc.ANSWERED), (lc.SENT, "close", lc.CLOSED), (lc.ANSWERED, "close", lc.CLOSED),
    (lc.ANSWERED, "reopen", lc.REOPENED), (lc.ANSWERED, "close_with_explanation", lc.EXPLAINED),
    (lc.REOPENED, "send", lc.SENT), (lc.REOPENED, "close", lc.CLOSED),
]
ACTIONS = ["approve", "send", "answer", "close", "reopen", "close_with_explanation"]


@pytest.mark.parametrize("state,action,nxt", LEGAL)
def test_legal_transitions(state, action, nxt):
    assert lc.STATES[state].apply(action, None) == nxt


def test_every_other_transition_is_illegal():
    legal = {(s, a) for s, a, _ in LEGAL}
    for s in lc.STATES:
        for a in ACTIONS:
            if (s, a) not in legal:
                with pytest.raises(lc.IllegalTransition):
                    lc.STATES[s].apply(a, None)


def test_terminal_states_have_no_exits():
    for s in (lc.CLOSED, lc.EXPLAINED):
        assert not lc.STATES[s].transitions


def test_priority_formula():
    assert priority("safety", "critical", 0) == 1.0
    assert priority("other", "minor", 0) == 0.06
    assert priority("safety", "major", 28) == pytest.approx(0.6 * 3.0)         # age weight 1 + 28/14 = 3
    assert age_weight(1000) == 3.0                                              # capped
    assert priority("safety", "critical", 0, "red") == 1.5 and priority("safety", "critical", 0, "amber") == 1.2


def _new_query(db):
    db.execute("INSERT INTO ops.check_failures (check_id, usubjid, site_id, src_table, src_pk, detected_on) VALUES ('chk_01','T','701','edc.vitals','1',%s) RETURNING id", (date(2026, 3, 6),))
    fid = db.execute("SELECT max(id) FROM ops.check_failures").fetchone()[0]
    return str(db.execute("INSERT INTO ops.queries (failure_id, site_id, usubjid, priority, state, text, opened_on) VALUES (%s,'701','T',1,'Draft','t',%s) RETURNING id", (fid, date(2026, 3, 6))).fetchone()[0])


def test_transitions_persist_state_events_and_audit(db):
    qid = _new_query(db)
    day = date(2026, 3, 7)
    for action, who in [("approve", "alice"), ("send", "system"), ("answer", "site"), ("reopen", "system"), ("send", "system"), ("answer", "site"), ("close", "alice")]:
        lc.transition(lc.Ctx(db, qid, day, who), action)
    state, reopen_count, approved_by = db.execute("SELECT state, reopen_count, approved_by FROM ops.queries WHERE id = %s", (qid,)).fetchone()
    assert (state, reopen_count, approved_by) == (lc.CLOSED, 1, "alice")
    events = [e for (e,) in db.execute("SELECT event FROM ops.query_events WHERE query_id = %s ORDER BY ts, event", (qid,))]
    assert sorted(events) == sorted(["approved", "sent", "answered", "reopened", "sent", "answered", "closed"])
    assert db.execute("SELECT count(*) FROM audit.log WHERE entity = 'query' AND entity_id = %s", (qid,)).fetchone()[0] == 7


def test_illegal_transition_changes_nothing(db):
    qid = _new_query(db)
    with pytest.raises(lc.IllegalTransition):
        lc.transition(lc.Ctx(db, qid, date(2026, 3, 7), "x"), "send")
    assert db.execute("SELECT state FROM ops.queries WHERE id = %s", (qid,)).fetchone()[0] == lc.DRAFT
