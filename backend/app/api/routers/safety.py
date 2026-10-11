"""Mock safety database intake and causality assessments (spec §13: /mock-safety/*, /causality/*, /recon/sae/cases/{id}/causality)."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.audit.logger import audit
from app.db.connection import get_pool, scoped_connection
from app.deps import Caller, get_caller
from app.domain.enums import Role
from app.recon.sae import mock_safety_api
from app.recon.sae.causality import CausalityAssessor
from app.recon.sae.e2b_mapper import E2BMapper
from app.sim.clock import TrialClock

router = APIRouter(tags=["safety"])
SUBMITTERS = (Role.DATA_MANAGER, Role.CENTRAL_MONITOR)
ASSESSORS = (Role.MEDICAL_MONITOR, Role.DATA_MANAGER)


class MessageIn(BaseModel):
    message: dict
    source_ae_id: int | None = None


def _rows(cur) -> list[dict]:
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/mock-safety/cases")
def post_case(body: MessageIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    if caller.role not in SUBMITTERS:
        raise HTTPException(403, "Only a data manager or central monitor can send a case to the safety database")
    with get_pool().connection() as conn:
        today = TrialClock(conn).today()
        ack = mock_safety_api.submit(conn, body.message, body.source_ae_id, today)
        audit(conn, today, caller.user, "mock_safety.submitted", "inbox", str(ack["id"]), {"status": ack["status"], "case": ack["safetyreportid"]}, role=caller.role.value)
    return ack


@router.post("/mock-safety/submit/{ae_id}")
def submit_ae(ae_id: int, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    """A person approves sending an EDC serious AE to the safety database: build the E2B message and deliver it."""
    if caller.role not in SUBMITTERS:
        raise HTTPException(403, "Only a data manager or central monitor can send a case to the safety database")
    with get_pool().connection() as conn:
        today = TrialClock(conn).today()
        msg = E2BMapper(conn).message_for_ae(ae_id, today)
        if msg is None:
            raise HTTPException(404, "that adverse event does not exist or is not serious")
        ack = mock_safety_api.submit(conn, msg, ae_id, today)
        audit(conn, today, caller.user, "mock_safety.submitted", "inbox", str(ack["id"]), {"status": ack["status"], "ae_id": ae_id}, role=caller.role.value)
    if ack["status"] == "rejected":
        raise HTTPException(409, "; ".join(ack["errors"]))
    return ack


@router.get("/mock-safety/cases")
def list_cases(caller: Annotated[Caller, Depends(get_caller)], status: str | None = None) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return _rows(conn.execute(
            "SELECT id, received_at, status, source_ae_id, message->'payload'->>'safetyreportid' AS safetyreportid, COALESCE((message->>'version')::int, 1) AS version, "
            "message->>'subject_ref' AS subject_ref, message->'payload'->'patient'->'reaction'->0->>'reactionmeddrapt' AS term, message->'errors' AS errors "
            "FROM mock_safety.inbox WHERE (%(s)s::text IS NULL OR status = %(s)s) ORDER BY id DESC LIMIT 200", {"s": status}))


@router.get("/mock-safety/cases/{inbox_id}")
def get_case(inbox_id: int, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        r = _rows(conn.execute("SELECT id, received_at, status, source_ae_id, message FROM mock_safety.inbox WHERE id = %s", (inbox_id,)))
    if not r:
        raise HTTPException(404, "unknown message")
    return r[0]


@router.post("/recon/sae/cases/{case_id}/causality")
def assess(case_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    if caller.role not in ASSESSORS:
        raise HTTPException(403, "Only a medical monitor or data manager can request a causality assessment")
    with scoped_connection(caller.role, caller.site_scope) as probe:
        if probe.execute("SELECT 1 FROM safety.v_cases WHERE safetyreportid = %s LIMIT 1", (case_id,)).fetchone() is None:
            raise HTTPException(404, "unknown case, or outside your site scope")
    with get_pool().connection() as conn:
        today = TrialClock(conn).today()
        out = CausalityAssessor(conn).assess(case_id, today, "on_demand")
        if out is None:
            raise HTTPException(409, "this case cannot be linked to a subject yet")
        audit(conn, today, caller.user, "causality.assessed", "case", case_id, {"category": out["category"], "escalate": out["escalate"]}, role=caller.role.value)
    return out


@router.get("/causality")
def list_assessments(caller: Annotated[Caller, Depends(get_caller)], case_id: str | None = None) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return [{**r, "id": str(r["id"])} for r in _rows(conn.execute(
            "SELECT id, case_id, usubjid, category, confidence, escalate, body, verification_status, created_at FROM ai.causality_assessments "
            "WHERE (%(c)s::text IS NULL OR case_id = %(c)s) ORDER BY created_at DESC LIMIT 100", {"c": case_id}))]


@router.get("/causality/{assessment_id}")
def get_assessment(assessment_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        r = _rows(conn.execute("SELECT id, case_id, usubjid, category, confidence, escalate, body, verification_status, created_at FROM ai.causality_assessments WHERE id = %s", (assessment_id,)))
    if not r:
        raise HTTPException(404, "unknown assessment")
    return {**r[0], "id": str(r[0]["id"])}
