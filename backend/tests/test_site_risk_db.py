from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.sim.daily_cycle import DailyCycle
from app.sim.reset import reset
from app.sites import risk

client = TestClient(app)


def test_risk_pipeline_scores_every_site_and_stores_history(db):
    reset(db)
    cycle = DailyCycle(db)
    for _ in range(35):
        cycle.run()
    day = db.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
    res = risk.compute_all(db, day)
    assert len(res["scores"]) >= 20 and all(0 <= s <= 100 for s in res["scores"].values())
    assert {k.kri for k in res["kris"]} == {"ae_rate", "sae_rate", "query_rate", "query_resolution_days", "entry_lag_days",
                                              "deviations_per_patient", "visit_window_violations", "screen_failure_rate"}
    assert all(k.rag in ("red", "amber", "green", "na") for k in res["kris"])      # "na": no usable comparison yet
    risk.store(db, day, res)
    n_sites = db.execute("SELECT count(*) FROM ops.site_risk WHERE sim_date = %s", (day,)).fetchone()[0]
    assert n_sites == len(res["scores"])
    assert db.execute("SELECT count(*) FROM ops.kri_values WHERE sim_date = %s", (day,)).fetchone()[0] == len(res["kris"])


def test_explanations_state_value_comparison_and_rule(db):
    reset(db)
    cycle = DailyCycle(db)
    for _ in range(40):
        cycle.run()
    day = db.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
    res = risk.compute_all(db, day)
    texts = [e["text"] for site, ks in _by_site(res).items() for e in risk.explain(ks, res["anomalies"].get(site, []))]
    assert texts and all("Rule:" in t or "p =" in t or "expected" in t or "identical" in t or "within" in t for t in texts)
    assert not any(w in " ".join(texts).lower() for w in ("fraud", "misconduct", "fabricat"))


def _by_site(res):
    out = {}
    for k in res["kris"]:
        out.setdefault(k.site_id, []).append(k)
    return out


def test_sites_api_ranks_and_gates_roles(db):
    # the API uses its own connection, so it sees committed data only; it must still answer cleanly
    r = client.get("/api/sites", headers={"X-Role": "central_monitor"})
    assert r.status_code == 200 and set(r.json()) == {"as_of", "kri_defs", "sites"}
    scores = [s["rule_score"] for s in r.json()["sites"]]
    assert scores == sorted(scores, reverse=True)
    assert client.get("/api/sites/NO-SUCH", headers={"X-Role": "central_monitor"}).status_code in (404, 403)
    assert client.get("/api/sites", headers={"X-Role": "study_lead"}).status_code == 200      # study lead sees site-level aggregates
