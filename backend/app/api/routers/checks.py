import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.audit.logger import audit
from app.checks import effectiveness
from app.checks.factory import CheckFactory, SpecError
from app.checks.generator import CheckGenerator
from app.checks.runner import load_specs
from app.db.connection import scoped_connection
from app.deps import Caller, get_caller
from app.domain.enums import Role
from app.sim.clock import TrialClock

router = APIRouter(tags=["checks"])


def _rows(cur) -> list[dict]:
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


class GenerateIn(BaseModel):
    use_llm: bool = True


class RejectIn(BaseModel):
    reason: str


def _dm(caller: Caller) -> None:
    if caller.role is not Role.DATA_MANAGER:
        raise HTTPException(403, "Only a data manager can decide on checks")


@router.post("/checks/generate")
def generate(body: GenerateIn, caller: Annotated[Caller, Depends(get_caller)]) -> list[dict]:
    """Propose checks from the protocol. Each is validated and dry-run; nothing runs until a data manager approves it."""
    _dm(caller)
    with scoped_connection(caller.role, caller.site_scope) as conn:
        gen = CheckGenerator(conn).generate(use_llm=body.use_llm, actor=caller.user, day=TrialClock(conn).today())
    return [g.__dict__ for g in gen]


@router.get("/checks/effectiveness")
def check_effectiveness(caller: Annotated[Caller, Depends(get_caller)]) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return effectiveness.in_app(conn)


def _decide(caller: Caller, check_id: str, approve: bool, reason: str | None = None) -> dict:
    _dm(caller)
    with scoped_connection(caller.role, caller.site_scope) as conn:
        row = conn.execute("SELECT approval_status, source FROM ops.check_specs WHERE id = %s FOR UPDATE", (check_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "unknown check")
        if row[0] != "pending_approval":
            raise HTTPException(409, f"check is already {row[0]}")
        day = TrialClock(conn).today()
        if approve:
            conn.execute("UPDATE ops.check_specs SET approval_status = 'approved', approved_by = %s, approved_at = now(), active = true WHERE id = %s", (caller.user, check_id))
        else:
            conn.execute("UPDATE ops.check_specs SET approval_status = 'rejected', approved_by = %s, approved_at = now(), active = false, "
                         "rationale = coalesce(rationale, '{}'::jsonb) || jsonb_build_object('rejected_reason', %s::text) WHERE id = %s", (caller.user, reason or "", check_id))
        audit(conn, day, caller.user, "check.approved" if approve else "check.rejected", "check_spec", check_id, {"reason": reason}, role=caller.role.value)
    return {"id": check_id, "approval_status": "approved" if approve else "rejected"}


@router.post("/checks/{check_id}/approve")
def approve_check(check_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    return _decide(caller, check_id, True)


@router.post("/checks/{check_id}/reject")
def reject_check(check_id: str, body: RejectIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    return _decide(caller, check_id, False, body.reason)


@router.post("/checks/{check_id}/dry-run")
def dry_run(check_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        spec = next((s for s in load_specs(conn, active_only=False) if s.id == check_id), None)
        if spec is None:
            raise HTTPException(404, "unknown check")
        try:
            fails = CheckFactory().compile(spec).run(conn)
        except SpecError as exc:
            raise HTTPException(422, str(exc))
    return {"id": check_id, "would_flag": len(fails), "sample": [f.model_dump() for f in fails[:10]]}


@router.get("/checks")
def list_checks(caller: Annotated[Caller, Depends(get_caller)]) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return _rows(conn.execute(
            "SELECT s.id, s.type, s.params->>'_description' AS description, s.ctq_category, s.severity, s.source, "
            "s.approval_status, s.rationale, s.approved_by, s.active, count(f.id) AS failures, count(f.id) FILTER (WHERE f.resolved_on IS NULL) AS open_failures "
            "FROM ops.check_specs s LEFT JOIN ops.check_failures f ON f.check_id = s.id GROUP BY s.id ORDER BY s.id"))


@router.get("/checks/{check_id}")
def get_check(check_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        rows = _rows(conn.execute("SELECT * FROM ops.check_specs WHERE id = %s", (check_id,)))
    if not rows:
        raise HTTPException(404, "unknown check")
    return rows[0]


@router.get("/failures")
def list_failures(caller: Annotated[Caller, Depends(get_caller)], check: str | None = None, site: str | None = None,
                  resolved: bool | None = None, limit: int = 200) -> list[dict]:
    where, params = ["true"], {"limit": min(limit, 1000)}
    for col, val in (("f.check_id", check), ("f.site_id", site)):
        if val:
            where.append(f"{col} = %({col.split('.')[1]})s")
            params[col.split(".")[1]] = val
    if resolved is not None:
        where.append("f.resolved_on IS NOT NULL" if resolved else "f.resolved_on IS NULL")
    if caller.site_scope:
        where.append("f.site_id = ANY(string_to_array(%(scope)s, ','))")
        params["scope"] = caller.site_scope
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return _rows(conn.execute(f"SELECT f.* FROM ops.check_failures f WHERE {' AND '.join(where)} ORDER BY f.detected_on DESC, f.id DESC LIMIT %(limit)s", params))
