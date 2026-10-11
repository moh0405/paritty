from datetime import date, timedelta

from app.checks import effectiveness
from app.checks.runner import sync_library
from app.queries import lifecycle as lc
from app.queries.digest import MINOR_PRIORITY, MinorIssueDigest, week_of
from app.sim.daily_cycle import DailyCycle
from app.sim.reset import reset


def mk_query(db, site, priority, state="Draft", check="chk_19b", pk="1", resolved=False):
    fid = db.execute("INSERT INTO ops.check_failures (check_id, usubjid, site_id, src_table, src_pk, detected_on, resolved_on) VALUES (%s,'01-701-1001',%s,'edc.vitals',%s,%s,%s) RETURNING id",
                     (check, site, pk, date(2026, 3, 2), date(2026, 3, 5) if resolved else None)).fetchone()[0]
    return str(db.execute("INSERT INTO ops.queries (failure_id, site_id, usubjid, priority, state, text, opened_on) VALUES (%s,%s,'01-701-1001',%s,%s,'t',%s) RETURNING id",
                          (fid, site, priority, state, date(2026, 3, 2))).fetchone()[0])


def test_week_starts_on_monday():
    assert week_of(date(2026, 3, 8)) == date(2026, 3, 2) and week_of(date(2026, 3, 2)) == date(2026, 3, 2)


def test_minor_queries_are_grouped_weekly_per_site_and_only_once(db):
    sync_library(db)      # a freshly seeded database (CI) has no check specs until the first simulated day
    db.execute("DELETE FROM ops.queries"); db.execute("DELETE FROM ops.digests")
    a, b, c = mk_query(db, "701", 0.06, pk="1"), mk_query(db, "701", 0.10, pk="2"), mk_query(db, "702", 0.05, pk="3")
    major = mk_query(db, "701", 0.9, pk="4")
    d = MinorIssueDigest(db)
    made = d.build_weekly(date(2026, 3, 9))
    assert len(made) == 2                                                     # one digest per site
    rows = {s: (q, t) for s, q, t in db.execute("SELECT site_id, query_ids, text FROM ops.digests")}
    assert {str(x) for x in rows["701"][0]} == {a, b} and major not in {str(x) for x in rows["701"][0]}
    assert "2 minor data issue" in rows["701"][1] and "01-701-1001" in rows["701"][1]
    assert d.build_weekly(date(2026, 3, 9)) == []                             # already included: no duplicate digest


def test_approving_a_digest_approves_its_queries_once(db):
    sync_library(db)      # a freshly seeded database (CI) has no check specs until the first simulated day
    db.execute("DELETE FROM ops.queries"); db.execute("DELETE FROM ops.digests")
    a, b = mk_query(db, "701", 0.06, pk="1"), mk_query(db, "701", 0.10, pk="2")
    d = MinorIssueDigest(db)
    (did,) = d.build_weekly(date(2026, 3, 9))
    assert d.approve(did, "alice", date(2026, 3, 9)) == 2
    assert {s for (s,) in db.execute("SELECT state FROM ops.queries")} == {"Approved"} and db.execute("SELECT state FROM ops.digests").fetchone()[0] == "Approved"
    try:
        d.approve(did, "alice", date(2026, 3, 9))
        assert False
    except lc.IllegalTransition:
        pass


def test_cycle_holds_minor_queries_for_the_weekly_digest(db):
    reset(db)
    cycle = DailyCycle(db)
    for _ in range(60):
        cycle.run()
    minor = db.execute("SELECT count(*) FROM ops.queries WHERE priority < %s", (MINOR_PRIORITY,)).fetchone()[0]
    in_digest = db.execute("SELECT coalesce(sum(array_length(query_ids, 1)), 0) FROM ops.digests").fetchone()[0]
    assert db.execute("SELECT count(*) FROM ops.digests").fetchone()[0] >= 1 and in_digest >= 1
    assert db.execute("SELECT count(*) FROM ops.queries WHERE state = 'Draft' AND priority >= %s", (MINOR_PRIORITY,)).fetchone()[0] == 0   # nothing important waits for approval in auto mode
    assert db.execute("SELECT count(*) FROM ops.digests WHERE state = 'Draft'").fetchone()[0] == 0


def test_effectiveness_counts_confirmed_and_dismissed_and_recommends_retirement(db):
    sync_library(db)      # a freshly seeded database (CI) has no check specs until the first simulated day
    db.execute("DELETE FROM ops.queries"); db.execute("DELETE FROM ops.check_failures")
    for i in range(2):
        mk_query(db, "701", 0.5, state="Closed", check="chk_01", pk=f"c{i}")
    for i in range(6):
        mk_query(db, "701", 0.5, state="ClosedWithExplanation", check="chk_02", pk=f"d{i}")
    mk_query(db, "701", 0.5, state="Sent", check="chk_03", pk="s")
    rows = {r["check_id"]: r for r in effectiveness.in_app(db)}
    assert (rows["chk_01"]["confirmed"], rows["chk_01"]["dismissed"], rows["chk_01"]["recommend_retire"]) == (2, 0, False)
    assert (rows["chk_02"]["dismissed"], rows["chk_02"]["dismissed_rate"], rows["chk_02"]["recommend_retire"]) == (6, 1.0, True)
    assert rows["chk_03"]["dismissed_rate"] is None and not rows["chk_03"]["recommend_retire"]
