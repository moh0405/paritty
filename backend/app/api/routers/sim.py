from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import jobs
from app.db.connection import get_pool
from app.deps import Caller, get_caller
from app.seed.common import connect
from app.sim.clock import TrialClock
from app.sim.daily_cycle import DailyCycle
from app.sim.reset import reset as reset_sim

router = APIRouter(prefix="/sim", tags=["sim"])


class AdvanceIn(BaseModel):
    days: int = Field(1, ge=1, le=400)
    auto_approve: bool = True   # simulated data manager approves drafts and accepts explanations (actor 'sim:auto', audited)


class ResetIn(BaseModel):
    seed: int | None = None


def clock_payload() -> dict:
    with get_pool().connection() as conn:
        c = TrialClock(conn)
        return {"today": c.today().isoformat(), "study_start": c.study_start().isoformat(), "study_day": c.study_day()}


@router.get("/clock")
def get_clock() -> dict:
    return clock_payload()


@router.post("/advance", status_code=202)
def advance(body: AdvanceIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    def work(progress):
        totals: dict[str, int] = {}
        with connect() as conn:
            cycle = DailyCycle(conn)
            for i in range(body.days):
                rep = cycle.run(auto_approve=body.auto_approve)
                conn.commit()
                for k in ("new_failures", "opened", "approved", "sent", "answered", "closed", "reopened", "explained"):
                    totals[k] = totals.get(k, 0) + getattr(rep, k)
                progress(i + 1, {"day": str(rep.day), **{k: v for k, v in rep.as_dict().items() if k != "day" and k != "released"}})
            conn.autocommit = True
            for agg in ("ops.query_aging_daily", "edc.site_vitals_weekly"):
                conn.execute(f"CALL refresh_continuous_aggregate('{agg}', NULL, NULL)")
        return {"days": body.days, "totals": totals, **clock_payload()}
    try:
        return {"job_id": jobs.start("sim.advance", body.days, work, exclusive="sim")}
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@router.post("/reset")
def reset(body: ResetIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    if "sim" in jobs._running:
        raise HTTPException(409, "simulation is busy")
    with connect() as conn:
        reset_sim(conn, body.seed)
        conn.commit()
    return clock_payload()
