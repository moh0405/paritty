"""What is waiting for the caller today (the 'Today' page and the sidebar badges)."""
from typing import Annotated

from fastapi import APIRouter, Depends

from app import attention
from app.db.connection import get_pool
from app.deps import Caller, get_caller
from app.sim.clock import TrialClock

router = APIRouter(prefix="/attention", tags=["attention"])


@router.get("")
def get_attention(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with get_pool().connection() as conn:       # counts only (no patient-level rows), so every role may read them; site scope still applies
        return attention.summary(conn, caller.role, TrialClock(conn).today(), caller.site_scope)
