from datetime import timedelta

from fastapi.testclient import TestClient

from app.forecast.service import ForecastService, Hypothetical
from app.main import app
from app.sim.daily_cycle import DailyCycle
from app.sim.reset import reset

client = TestClient(app)


def test_forecast_after_some_days_is_ordered_stored_and_deterministic(db):
    reset(db)
    cycle = DailyCycle(db)
    for _ in range(14):
        cycle.run()
    day = db.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
    a = ForecastService(db, n_sims=600).run(day)
    b = ForecastService(db, n_sims=600).run(day)
    assert a["p10"] <= a["p50"] <= a["p90"] and a["p50"] > day and a["p50"] == b["p50"]
    assert a["readiness"]["total"] == 7 and 0 <= a["readiness"]["met"] <= 7
    stored = db.execute("SELECT count(*) FROM ops.lock_forecasts").fetchone()[0]
    assert stored >= 14                                              # the daily cycle stores a forecast every day
    assert a["blockers"] and all(x["delta_p50_days"] > 0 for x in a["blockers"])
    assert a["benchmark"]["tufts_days"] == 36


def test_forecast_moves_later_when_more_work_is_open(db):
    reset(db)
    for _ in range(10):
        DailyCycle(db).run()
    day = db.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
    base = ForecastService(db, n_sims=800).run(day)["p50"]
    faster = ForecastService(db, n_sims=800).run(day, Hypothetical(close_categories=["expected", "safety", "other", "efficacy", "eligibility", "sae_recon"]))["p50"]
    assert faster <= base


def test_forecast_api_shapes_and_roles(db):
    for role in ("study_lead", "data_manager"):
        r = client.get("/api/lock/forecast", headers={"X-Role": role})
        assert r.status_code == 200 and {"p10", "p50", "p90", "readiness", "blockers"} <= set(r.json())
    r = client.get("/api/lock/readiness", headers={"X-Role": "study_lead"}).json()
    assert r["total"] == 7 and len(r["criteria"]) == 7
    assert isinstance(client.get("/api/lock/forecast/history", headers={"X-Role": "study_lead"}).json(), list)
