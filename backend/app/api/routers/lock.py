from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.db.connection import get_pool, scoped_connection
from app.deps import Caller, get_caller
from app.forecast.service import ForecastService
from app.sim.clock import TrialClock

router = APIRouter(prefix="/lock", tags=["lock"])


def _latest(conn) -> dict | None:
    r = conn.execute("SELECT sim_date, p10, p50, p90, readiness, blockers, n_sims FROM ops.lock_forecasts ORDER BY sim_date DESC LIMIT 1").fetchone()
    return None if r is None else {"sim_date": r[0], "p10": r[1], "p50": r[2], "p90": r[3], "readiness": r[4], "blockers": r[5], "n_sims": r[6]}


def _live() -> dict:
    """No stored forecast yet (before the first simulated day): compute one from the system connection. Aggregate output only."""
    with get_pool().connection() as conn:
        res = ForecastService(conn, n_sims=500).run(TrialClock(conn).today())
    return {"sim_date": res["sim_date"], "p10": res["p10"], "p50": res["p50"], "p90": res["p90"], "n_sims": res["n_sims"], "blockers": res["blockers"],
            "readiness": {"criteria": res["readiness"]["criteria"], "met": res["readiness"]["met"], "total": res["readiness"]["total"],
                          "benchmark": res["benchmark"], "enrollment": res["enrollment"], "items": res["items"]}}


@router.get("/forecast")
def forecast(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        latest = _latest(conn)
    return latest or _live()


@router.get("/readiness")
def readiness(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    f = forecast(caller)
    r = f["readiness"]
    return {"sim_date": f["sim_date"], "met": r["met"], "total": r["total"], "criteria": r["criteria"]}


@router.get("/forecast/history")
def history(caller: Annotated[Caller, Depends(get_caller)]) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return [{"day": str(d), "p10": str(a), "p50": str(b), "p90": str(c), "met": met}
                for d, a, b, c, met in conn.execute("SELECT sim_date, p10, p50, p90, readiness->>'met' FROM ops.lock_forecasts ORDER BY sim_date")]


# ---- what-if and backtest -----------------------------------------------------------------------------
import subprocess
import sys
from pathlib import Path

import psycopg
from pydantic import BaseModel, Field

from app import jobs
from app.audit.logger import audit
from app.config import get_settings
from app.domain.enums import Role
from app.forecast.service import Hypothetical
from app.forecast.whatif import WhatIfError, WhatIfRunner

PLANNERS = (Role.DATA_MANAGER, Role.CENTRAL_MONITOR, Role.STUDY_LEAD)
BACKEND = Path(__file__).resolve().parents[3]


class WhatIfIn(BaseModel):
    site_response_days: dict[str, float] = Field(default_factory=dict)      # e.g. {"705": 3}
    close_categories: list[str] = Field(default_factory=list)               # e.g. ["sae_recon"]


class BacktestIn(BaseModel):
    at_day: int = Field(120, ge=61, le=400)       # study day on which the forecast to be tested is made


@router.post("/whatif")
def whatif(body: WhatIfIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    if caller.role not in PLANNERS:
        raise HTTPException(403, "Your role cannot run what-if forecasts")
    with get_pool().connection() as conn:
        today = TrialClock(conn).today()
        try:
            out = WhatIfRunner(conn).run(today, Hypothetical(site_response_days=body.site_response_days, close_categories=body.close_categories))
        except WhatIfError as exc:
            raise HTTPException(422, str(exc))
        audit(conn, today, caller.user, "lock.whatif", "forecast", str(today), {"description": out["description"], "delta_p50_days": out["delta_p50_days"]}, role=caller.role.value)
    return out


@router.post("/backtest", status_code=202)
def backtest(body: BacktestIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    """Fork the golden database, simulate to study day N, then to completion, and compare the day-N forecast with the realised lock date."""
    if caller.role not in PLANNERS:
        raise HTTPException(403, "Your role cannot run a backtest")
    advance = body.at_day - get_settings().sim_start_day

    def work(progress):
        proc = subprocess.run([sys.executable, "-W", "ignore", "-m", "app.evals.run", "--scenario", "forecast_backtest", "--advance-days", str(advance)],
                              cwd=BACKEND, capture_output=True, text=True)
        progress(1, {"exit": proc.returncode})
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-600:])
        return {"output": proc.stdout[-1500:]}
    try:
        return {"job_id": jobs.start("lock.backtest", 1, work, exclusive="eval"), "advance_days": advance}
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@router.get("/backtests")
def backtests(caller: Annotated[Caller, Depends(get_caller)], limit: int = 5) -> list[dict]:
    """Recent backtest results with the forecast-versus-actual table (aggregate evaluation data, no patient rows)."""
    with psycopg.connect(get_settings().eval_admin_url) as c:
        runs = c.execute("SELECT id, started_at, status FROM eval.scenario_runs WHERE scenario = 'forecast_backtest' ORDER BY started_at DESC LIMIT %s", (min(limit, 20),)).fetchall()
        out = []
        for rid, started, status in runs:
            m = {metric: (value, detail) for metric, value, detail in c.execute("SELECT metric, value, detail FROM eval.metrics WHERE scenario_run_id = %s AND module = 'forecast'", (rid,))}
            out.append({"id": str(rid), "started_at": started, "status": status, "metrics": {k: v[0] for k, v in m.items() if k != "checkpoints"},
                        "forecast_day": (m.get("abs_error_days") or (0, {}))[1].get("forecast_day"), "p50": (m.get("abs_error_days") or (0, {}))[1].get("p50"),
                        "actual_lock": (m.get("abs_error_days") or (0, {}))[1].get("actual_lock"), "checkpoints": (m.get("checkpoints") or (0, {}))[1].get("rows", [])})
    return out
