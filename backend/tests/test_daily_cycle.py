from app.sim.daily_cycle import DailyCycle
from app.sim.reset import reset


def test_thirty_days_open_close_and_reopen_queries(db):
    reset(db)
    cycle = DailyCycle(db)
    totals = {}
    for _ in range(30):
        rep = cycle.run()
        for k in ("new_failures", "opened", "answered", "closed", "reopened", "explained"):
            totals[k] = totals.get(k, 0) + getattr(rep, k)
    assert totals["opened"] > 20 and totals["closed"] > 5 and totals["reopened"] >= 1
    assert db.execute("SELECT today FROM ops.sim_clock").fetchone()[0].isoformat() == "2026-04-05"
    assert db.execute("SELECT count(*) FROM audit.log WHERE action LIKE 'query.%'").fetchone()[0] > 50


def test_no_query_is_approved_without_an_approver(db):
    reset(db)
    cycle = DailyCycle(db)
    for _ in range(5):
        cycle.run(auto_approve=False)
    assert db.execute("SELECT count(*) FROM ops.queries WHERE state <> 'Draft'").fetchone()[0] == 0   # humans must approve first
    assert db.execute("SELECT count(*) FROM ops.queries").fetchone()[0] > 0


def test_same_seed_gives_identical_runs(db):
    def run():
        reset(db, 7)
        cycle = DailyCycle(db)
        for _ in range(15):
            cycle.run()
        return db.execute("SELECT state, count(*) FROM ops.queries GROUP BY 1 ORDER BY 1").fetchall()
    assert run() == run()
