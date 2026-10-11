"""Drafts awaiting a human: review notes, letters, agendas, eligibility answers and agent actions (spec §2 rule 2, §13)."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.audit.logger import audit
from app.db.connection import get_pool, scoped_connection
from app.deps import Caller, get_caller
from app.domain.enums import Role
from app.sim.clock import TrialClock

router = APIRouter(prefix="/drafts", tags=["drafts"])

# who may approve which kind of draft; only a medical monitor signs a review note
APPROVERS: dict[str, set[Role]] = {
    "note": {Role.MEDICAL_MONITOR}, "letter": {Role.CENTRAL_MONITOR, Role.DATA_MANAGER}, "agenda": {Role.CENTRAL_MONITOR, Role.DATA_MANAGER},
    "eligibility": {Role.MEDICAL_MONITOR, Role.DATA_MANAGER}, "agent_action": {Role.DATA_MANAGER, Role.STUDY_LEAD},
}
KINDS = set(APPROVERS)
EDITABLE_STATES = ("draft",)


class EditIn(BaseModel):
    text: str


class ReasonIn(BaseModel):
    reason: str | None = None


def _rows(cur) -> list[dict]:
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _today():
    with get_pool().connection() as c:
        return TrialClock(c).today()


@router.get("")
def list_drafts(caller: Annotated[Caller, Depends(get_caller)], kind: str | None = None, state: str | None = None, site: str | None = None,
                subject: str | None = None, limit: int = 200) -> list[dict]:
    where, params = ["true"], {"limit": min(limit, 500)}
    for col, val in (("kind", kind), ("state", state), ("site_id", site), ("subject_ref", subject)):
        if val:
            where.append(f"{col} = %({col})s")
            params[col] = val
    if caller.site_scope:
        where.append("(site_id IS NULL OR site_id = ANY(string_to_array(%(scope)s, ',')))")
        params["scope"] = caller.site_scope
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return _rows(conn.execute(f"SELECT id, kind, subject_ref, site_id, body, state, approved_by, approved_at, created_at FROM ops.drafts WHERE {' AND '.join(where)} "
                                  f"ORDER BY created_at DESC LIMIT %(limit)s", params))


@router.get("/{draft_id}")
def get_draft(draft_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        r = _rows(conn.execute("SELECT id, kind, subject_ref, site_id, body, state, approved_by, approved_at, created_at FROM ops.drafts WHERE id = %s", (draft_id,)))
    if not r:
        raise HTTPException(404, "unknown draft")
    return r[0]


def _decide(caller: Caller, draft_id: str, new_state: str, reason: str | None = None) -> dict:
    with get_pool().connection() as conn:           # decisions are system writes; authorization is the role check below
        row = conn.execute("SELECT kind, state FROM ops.drafts WHERE id = %s FOR UPDATE", (draft_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "unknown draft")
        kind, state = row
        if caller.role not in APPROVERS.get(kind, set()):
            raise HTTPException(403, f"Only {', '.join(sorted(r.value for r in APPROVERS.get(kind, set())))} can decide a {kind}")
        if state not in ("draft", "approved") or (new_state == "approved" and state != "draft") or (new_state == "signed" and state not in ("draft", "approved")):
            raise HTTPException(409, f"a {state} draft cannot become {new_state}")
        if new_state == "signed" and kind != "note":
            raise HTTPException(422, "only review notes are signed")
        conn.execute("UPDATE ops.drafts SET state = %s, approved_by = %s, approved_at = %s WHERE id = %s", (new_state, caller.user, datetime.now(timezone.utc), draft_id))
        today = TrialClock(conn).today()
        audit(conn, today, caller.user, f"draft.{new_state}", "draft", draft_id, {"kind": kind, "reason": reason}, role=caller.role.value)
        if kind == "agent_action" and new_state == "approved":
            from app.agent.apply import apply_action
            apply_action(conn, draft_id, today, caller.user)
    return {"id": draft_id, "state": new_state}


@router.post("/{draft_id}/approve")
def approve(draft_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    return _decide(caller, draft_id, "approved")


@router.post("/{draft_id}/reject")
def reject(draft_id: str, body: ReasonIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    return _decide(caller, draft_id, "rejected", body.reason)


@router.post("/{draft_id}/sign")
def sign(draft_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    return _decide(caller, draft_id, "signed")


@router.patch("/{draft_id}")
def edit(draft_id: str, body: EditIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with get_pool().connection() as conn:
        row = conn.execute("SELECT kind, state, body FROM ops.drafts WHERE id = %s FOR UPDATE", (draft_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "unknown draft")
        kind, state, draft_body = row
        if caller.role not in APPROVERS.get(kind, set()):
            raise HTTPException(403, f"Only {', '.join(sorted(r.value for r in APPROVERS.get(kind, set())))} can edit a {kind}")
        if state not in EDITABLE_STATES:
            raise HTTPException(409, "only drafts can be edited")
        draft_body = {**(draft_body or {}), "text": body.text, "edited_by": caller.user}
        import json
        conn.execute("UPDATE ops.drafts SET body = %s WHERE id = %s", (json.dumps(draft_body), draft_id))
        audit(conn, TrialClock(conn).today(), caller.user, "draft.edited", "draft", draft_id, {"kind": kind}, role=caller.role.value)
    return {"id": draft_id, "state": "draft"}
