from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.audit.logger import audit
from app.db.connection import get_pool, scoped_connection
from app.deps import Caller, get_caller
from app.domain.enums import Role
from app.medical.service import MedicalService
from app.recon.refs import irt_refs
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
    for p in pts:
        p["arm"] = next((arm[r] for r in irt_refs(p["usubjid"]) if r in arm), None)
    with get_pool().connection() as sysconn:
        audit(sysconn, today, caller.user, "unblinded.view", "edish", None, {"points": len(pts)}, role=caller.role.value)
    return {"thresholds": {"aminotransferase": 3, "bilirubin": 2}, "points": pts, "unblinded": True}
