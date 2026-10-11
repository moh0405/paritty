from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.db.connection import scoped_connection
from app.deps import Caller, get_caller
from app.domain.enums import Role
from app.queries import lifecycle as lc
from app.queries.digest import MinorIssueDigest
from app.sim.clock import TrialClock

router = APIRouter(prefix="/digests", tags=["digests"])


@router.get("")
def list_digests(caller: Annotated[Caller, Depends(get_caller)], state: str | None = None) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        cur = conn.execute("SELECT id, site_id, week_of, array_length(query_ids, 1) AS queries, text, state FROM ops.digests WHERE (%(s)s::text IS NULL OR state = %(s)s) "
                           "AND (%(scope)s::text IS NULL OR site_id = ANY(string_to_array(%(scope)s, ','))) ORDER BY week_of DESC, site_id LIMIT 200",
                           {"s": state, "scope": caller.site_scope})
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/{digest_id}/approve")
def approve(digest_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    if caller.role is not Role.DATA_MANAGER:
        raise HTTPException(403, "Only a data manager can approve a digest")
    with scoped_connection(caller.role, caller.site_scope) as conn:
        try:
            n = MinorIssueDigest(conn).approve(digest_id, caller.user, TrialClock(conn).today())
        except KeyError:
            raise HTTPException(404, "unknown digest")
        except lc.IllegalTransition as exc:
            raise HTTPException(409, str(exc))
    return {"id": digest_id, "approved_queries": n}
