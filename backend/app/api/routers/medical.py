from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.audit.logger import audit
from app.db.connection import get_pool, scoped_connection
from app.deps import Caller, get_caller
from app.domain.enums import Role
from app.medical.service import MedicalService
from app.hub.crosswalk import SubjectMap
from app.sim.clock import TrialClock

router = APIRouter(tags=["medical"])


class UnblindIn(BaseModel):
    reason: str


@router.get("/medical/review-list")
def review_list(caller: Annotated[Caller, Depends(get_caller)], limit: int = 200) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        today = TrialClock(conn).today()
        svc = MedicalService(conn)
        items = svc.review_items(today)[:limit]
        reviews = {k: (str(i), rs) for k, i, rs in conn.execute(
            "SELECT body->>'key', id, review_status FROM ai.findings WHERE module = 'medical' AND body->>'key' IS NOT NULL")}
    return [{"type": it.type, "score": round(it.score, 1), "title": it.title, "day": it.event_day, "usubjid": it.usubjid, "site_id": it.site_id,
             "finding_id": reviews.get(it.finding_key, (None, None))[0], "review_status": reviews.get(it.finding_key, (None, "open"))[1],
             "rule": it.detail["rule"]} for it in items]


@router.get("/medical/patients/{usubjid}/profile")
def profile(usubjid: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        p = MedicalService(conn).profile(usubjid)
    if p is None:
        raise HTTPException(404, "unknown subject, or outside your site scope")
    return p


@router.get("/medical/edish")
def edish(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    """Blinded eDISH points: no treatment arm in any field."""
    with scoped_connection(caller.role, caller.site_scope) as conn:
        pts = MedicalService(conn).edish()
    return {"thresholds": {"aminotransferase": 3, "bilirubin": 2}, "points": pts}


@router.post("/unblind")
def unblind(body: UnblindIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    if caller.role is not Role.UNBLINDED_STATISTICIAN:
        raise HTTPException(403, "Only the unblinded statistician can unblind")
    if len(body.reason.strip()) < 5:
        raise HTTPException(422, "A reason is required")
    with get_pool().connection() as conn:     # system writes: the role gate above is the authorization; this role has no write grants by design
        today = TrialClock(conn).today()
        conn.execute("INSERT INTO ops.sim_state (key, value) VALUES (%s, to_jsonb(%s::text)) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                     (f"unblind:{caller.user}", body.reason))
        audit(conn, today, caller.user, "unblind", "session", caller.user, {"reason": body.reason}, role=caller.role.value)
    return {"unblinded": True}


@router.get("/unblinded/edish")
def unblinded_edish(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    """eDISH points with treatment arm, for the unblinded statistician after a logged unblinding. Every call is audit-logged."""
    if caller.role is not Role.UNBLINDED_STATISTICIAN:
        raise HTTPException(403, "Only the unblinded statistician can see treatment arm")
    with scoped_connection(Role.DATA_MANAGER, None) as conn:           # patient-level lab data comes from the blinded side
        today = TrialClock(conn).today()
        pts = MedicalService(conn).edish()
    with get_pool().connection() as sysconn:
        if not sysconn.execute("SELECT 1 FROM ops.sim_state WHERE key = %s", (f"unblind:{caller.user}",)).fetchone():
            raise HTTPException(403, "Unblind first (POST /api/unblind with a reason)")
    with scoped_connection(caller.role, None) as conn:                  # the arm itself is read under the unblinded role
        arm = {r: a for r, a in conn.execute("SELECT patient_ref, arm FROM unblinded.randomization")}
    with get_pool().connection() as sysconn:
        smap = SubjectMap(sysconn)
    for p in pts:
        p["arm"] = next((arm[r] for r in smap.sources_for("irt", p["usubjid"]) if r in arm), None)
    with get_pool().connection() as sysconn:
        audit(sysconn, today, caller.user, "unblinded.view", "edish", None, {"points": len(pts)}, role=caller.role.value)
    return {"thresholds": {"aminotransferase": 3, "bilirubin": 2}, "points": pts, "unblinded": True}


# ---- trends, clusters ------------------------------------------------------------------------------
@router.get("/medical/trends")
def trends(caller: Annotated[Caller, Depends(get_caller)], test: str = "ALT", by: str = "site") -> dict:
    from app.medical.trends import lab_trends
    with scoped_connection(caller.role, caller.site_scope) as conn:
        try:
            return lab_trends(conn, test, by)
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@router.get("/medical/clusters")
def clusters(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        svc = MedicalService(conn)
        return {"ae_clusters": [c.__dict__ for c in svc.clusters()], "alt_creep": [c.__dict__ for c in svc.creep()]}


# ---- review notes ----------------------------------------------------------------------------------
@router.post("/medical/patients/{usubjid}/notes")
def draft_note(usubjid: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    """Draft (or return the existing) review note for a flagged subject. A medical monitor edits and signs it via /api/drafts."""
    from app.medical.notes import NoteDrafter
    if caller.role not in (Role.MEDICAL_MONITOR, Role.DATA_MANAGER):
        raise HTTPException(403, "Only a medical monitor or data manager can draft a review note")
    with scoped_connection(caller.role, caller.site_scope) as probe:
        if probe.execute("SELECT 1 FROM edc.subjects WHERE usubjid = %s", (usubjid,)).fetchone() is None:
            raise HTTPException(404, "unknown subject, or outside your site scope")
    with get_pool().connection() as conn:
        today = TrialClock(conn).today()
        did = NoteDrafter(conn).draft(usubjid, today)
        if did is None:
            raise HTTPException(409, "this subject has no flagged findings to write a note about")
        audit(conn, today, caller.user, "note.drafted", "draft", did, {"usubjid": usubjid}, role=caller.role.value)
    return {"draft_id": did}


# ---- escalation log --------------------------------------------------------------------------------
class EscalateIn(BaseModel):
    reason: str
    usubjid: str | None = None
    finding_id: str | None = None


class EscalationUpdate(BaseModel):
    status: str
    resolution: str | None = None


ESCALATION_ROLES = (Role.MEDICAL_MONITOR, Role.DATA_MANAGER, Role.CENTRAL_MONITOR)


@router.post("/medical/escalations")
def raise_escalation(body: EscalateIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    if caller.role not in ESCALATION_ROLES:
        raise HTTPException(403, "Your role cannot raise an escalation")
    if len(body.reason.strip()) < 5:
        raise HTTPException(422, "Say why this needs a person")
    with get_pool().connection() as conn:
        eid = str(conn.execute("INSERT INTO ops.escalations (usubjid, finding_id, reason, raised_by, status) VALUES (%s,%s,%s,%s,'open') RETURNING id",
                               (body.usubjid, body.finding_id, body.reason, caller.user)).fetchone()[0])
        audit(conn, TrialClock(conn).today(), caller.user, "escalation.raised", "escalation", eid, {"usubjid": body.usubjid}, role=caller.role.value)
    return {"id": eid, "status": "open"}


@router.get("/medical/escalations")
def list_escalations(caller: Annotated[Caller, Depends(get_caller)], status: str | None = None) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        cur = conn.execute("SELECT id, usubjid, finding_id, reason, raised_by, raised_at, status, resolution FROM ops.escalations "
                           "WHERE (%(s)s::text IS NULL OR status = %(s)s) ORDER BY raised_at DESC LIMIT 200", {"s": status})
        cols = [d.name for d in cur.description]
        return [{**dict(zip(cols, r)), "id": str(r[0]), "finding_id": str(r[2]) if r[2] else None} for r in cur.fetchall()]


@router.patch("/medical/escalations/{escalation_id}")
def update_escalation(escalation_id: str, body: EscalationUpdate, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    if caller.role not in (Role.MEDICAL_MONITOR, Role.CENTRAL_MONITOR):
        raise HTTPException(403, "Only a medical or central monitor can update an escalation")
    if body.status not in ("open", "acknowledged", "resolved"):
        raise HTTPException(422, "status must be open, acknowledged or resolved")
    if body.status == "resolved" and not (body.resolution or "").strip():
        raise HTTPException(422, "Say how it was resolved")
    with get_pool().connection() as conn:
        n = conn.execute("UPDATE ops.escalations SET status = %s, resolution = COALESCE(%s, resolution) WHERE id = %s", (body.status, body.resolution, escalation_id)).rowcount
        if not n:
            raise HTTPException(404, "unknown escalation")
        audit(conn, TrialClock(conn).today(), caller.user, f"escalation.{body.status}", "escalation", escalation_id, {"resolution": body.resolution}, role=caller.role.value)
    return {"id": escalation_id, "status": body.status}
