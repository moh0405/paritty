import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.forecast import backtest
from app.forecast.service import Hypothetical
from app.forecast.whatif import WhatIfError, WhatIfRunner, describe, validate
from app.main import app
from app.sim.daily_cycle import DailyCycle
from app.sim.reset import reset

client = TestClient(app)


def test_description_is_plain_english():
    h = Hypothetical(site_response_days={"705": 3.0}, close_categories=["sae_recon"])
    d = describe(h)
    assert d == "If site 705 answers queries in about 3 days and serious adverse event reconciliation queries are already done" or "705" in d
    assert "reconciliation" in d


def test_validation_rejects_bad_hypotheticals(db):
    for bad, msg in ((Hypothetical(), "at least one change"), (Hypothetical(site_response_days={"999": 3}), "unknown site"),
                     (Hypothetical(site_response_days={"705": 0.0}), "between"), (Hypothetical(site_response_days={"705": 400}), "between"),
                     (Hypothetical(close_categories=["nonsense"]), "unknown work category")):
        with pytest.raises(WhatIfError, match=msg):
            validate(db, bad)
    validate(db, Hypothetical(site_response_days={"705": 3}, close_categories=["expected"]))


def test_what_if_is_deterministic_and_a_faster_site_cannot_make_lock_later(db):
    reset(db)
    cycle = DailyCycle(db)
    for _ in range(45):
        cycle.run()
    today = db.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
    site = db.execute("SELECT site_id FROM ops.queries GROUP BY 1 ORDER BY count(*) DESC LIMIT 1").fetchone()[0]
    runner = WhatIfRunner(db, n_sims=600)
    h = lambda: Hypothetical(site_response_days={site: 1.0})  # noqa: E731
    a, b = runner.run(today, h()), runner.run(today, h())
    assert a == b                                                         # same draws, same answer
    assert a["delta_p50_days"] <= 0 and a["delta_p90_days"] <= 0         # answering faster never delays lock
    assert a["baseline"]["p10"] <= a["baseline"]["p50"] <= a["baseline"]["p90"] and a["what_if"]["p10"] <= a["what_if"]["p50"] <= a["what_if"]["p90"]
    done = runner.run(today, Hypothetical(close_categories=["expected"]))
    assert done["delta_p50_days"] <= 0
    assert db.execute("SELECT count(*) FROM ops.lock_forecasts WHERE sim_date = %s", (today,)).fetchone()[0] >= 1        # the baseline day itself is untouched


def test_checkpoint_errors_and_coverage(db):
    d0 = date(2026, 6, 1)
    for i in range(0, 100, 10):
        day = d0 + timedelta(days=i)
        p50 = date(2027, 1, 31) + timedelta(days=(100 - i) // 5)         # forecasts converge on the realised date as time passes
        db.execute("INSERT INTO ops.lock_forecasts (sim_date, p10, p50, p90, readiness, blockers, n_sims) VALUES (%s,%s,%s,%s,'{}','[]',100)",
                   (day, p50 - timedelta(days=30), p50, p50 + timedelta(days=30)))
    actual = date(2027, 1, 31)
    rows = backtest.checkpoint_errors(db, d0, actual)
    assert [r["error_days"] for r in rows][0] > [r["error_days"] for r in rows][-1] >= 0 or len(rows) == 1
    assert all(r["covered"] for r in rows) and rows[0]["forecast_date"] == str(d0)
    assert rows[0]["days_before_lock"] == (actual - d0).days


def test_realised_ready_date_is_the_latest_finished_work(db):
    reset(db)
    ready = backtest.realised_ready_date(db)
    assert ready >= db.execute("SELECT max(entered_at) FROM edc.ae").fetchone()[0]
    db.execute("INSERT INTO ops.queries (site_id, usubjid, priority, state, text, opened_on, closed_on) VALUES ('701','u',1,'Closed','t','2026-01-01','2030-01-01')")
    assert backtest.realised_ready_date(db) == date(2030, 1, 1)


def test_whatif_and_backtest_endpoints_enforce_roles_and_validate():
    dm, sl = {"X-Role": "data_manager"}, {"X-Role": "study_lead"}
    assert client.post("/api/lock/whatif", json={"close_categories": ["expected"]}, headers={"X-Role": "medical_monitor"}).status_code == 403
    assert client.post("/api/lock/whatif", json={}, headers=sl).status_code == 422
    assert client.post("/api/lock/whatif", json={"site_response_days": {"999": 2}}, headers=dm).status_code == 422
    ok = client.post("/api/lock/whatif", json={"close_categories": ["expected"]}, headers=sl)
    assert ok.status_code == 200 and {"baseline", "what_if", "delta_p50_days", "description"} <= set(ok.json())
    assert client.post("/api/lock/backtest", json={"at_day": 10}, headers=dm).status_code == 422
    assert client.post("/api/lock/backtest", json={"at_day": 120}, headers={"X-Role": "medical_monitor"}).status_code == 403
    assert client.get("/api/lock/backtests", headers=dm).status_code == 200
