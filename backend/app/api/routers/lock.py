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
