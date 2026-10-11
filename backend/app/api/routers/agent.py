"""Data-manager agent (spec §13): proposals are drafts; approve/reject through /api/drafts."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agent.data_manager import DataManagerAgent
from app.audit.logger import audit
from app.db.connection import get_pool, scoped_connection
from app.deps import Caller, get_caller
from app.domain.enums import Role
from app.sim.clock import TrialClock

router = APIRouter(prefix="/agent", tags=["agent"])
ALLOWED = (Role.DATA_MANAGER, Role.STUDY_LEAD)


class EnableIn(BaseModel):
    enabled: bool


@router.post("/plan")
def plan(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    """Ask the agent for up to five proposed actions now. Nothing takes effect until a person approves each one."""
    if caller.role not in ALLOWED:
        raise HTTPException(403, "Only a data manager or study lead can ask the agent for a plan")
    with get_pool().connection() as conn:
        today = TrialClock(conn).today()
        ids = DataManagerAgent(conn).plan(today, actor=caller.user)
        audit(conn, today, caller.user, "agent.plan", "agent", None, {"proposed": len(ids)}, role=caller.role.value)
    return {"proposed": len(ids), "draft_ids": ids}


@router.get("/actions")
def actions(caller: Annotated[Caller, Depends(get_caller)], state: str | None = None) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        cur = conn.execute("SELECT id, site_id, body, state, approved_by, approved_at, created_at FROM ops.drafts WHERE kind = 'agent_action' AND (%(s)s::text IS NULL OR state = %(s)s) "
                           "ORDER BY created_at DESC LIMIT 100", {"s": state})
        cols = [d.name for d in cur.description]
        return [{**dict(zip(cols, r)), "id": str(r[0])} for r in cur.fetchall()]


@router.get("/status")
def status(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with get_pool().connection() as conn:
        on = conn.execute("SELECT value FROM ops.sim_state WHERE key = 'agent_enabled'").fetchone()
        factors = {k.split(":", 1)[1]: float(v) for k, v in conn.execute("SELECT key, value FROM ops.sim_state WHERE key LIKE 'response_factor:%'")}
    return {"enabled": bool(on and on[0] is True), "approved_speedups": factors}


@router.post("/enable")
def enable(body: EnableIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    """Switch weekly proposals in the simulation on or off (with auto-approve on, the simulated data manager approves them)."""
    if caller.role not in ALLOWED:
        raise HTTPException(403, "Only a data manager or study lead can switch the agent on or off")
    with get_pool().connection() as conn:
        conn.execute("INSERT INTO ops.sim_state (key, value) VALUES ('agent_enabled', %s::jsonb) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", ("true" if body.enabled else "false",))
        audit(conn, TrialClock(conn).today(), caller.user, "agent.enabled" if body.enabled else "agent.disabled", "agent", None, {}, role=caller.role.value)
    return {"enabled": body.enabled}
