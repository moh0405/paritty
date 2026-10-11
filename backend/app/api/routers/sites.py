from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.db.connection import get_pool, scoped_connection
from app.deps import Caller, get_caller
from app.domain.enums import Role
from app.queries.aging import aging_by_site
from app.sim.clock import TrialClock
from app.sites import issues as site_issues
from app.sites import scorecard_pdf, visit_planner
from app.sites.kris import KRI_DEFS
from app.sites.letters import NothingToRaise, SiteDrafter

router = APIRouter(prefix="/sites", tags=["sites"])
issues_router = APIRouter(prefix="/issues", tags=["sites"])
MONITORS = {Role.CENTRAL_MONITOR, Role.DATA_MANAGER}      # who drafts site documents and works issues (same roles approve them)


class IssueIn(BaseModel):
    status: str | None = None
    owner: str | None = None


def _monitor(caller: Caller) -> None:
    if caller.role not in MONITORS:
        raise HTTPException(403, f"Only {', '.join(sorted(r.value for r in MONITORS))} can do this")


def _latest(conn) -> date | None:
    return conn.execute("SELECT max(sim_date) FROM ops.site_risk").fetchone()[0]


def _allowed(caller: Caller, site: str) -> bool:
    return not caller.site_scope or site in caller.site_scope.split(",")


@router.get("")
def list_sites(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        day = _latest(conn)
        if day is None:
            return {"as_of": None, "kri_defs": {}, "sites": []}
        names = {s: (n, subj) for s, n, subj in conn.execute("SELECT site_id, name, subjects FROM hub.v_site_summary")}
        kri: dict[str, dict] = {}
        for s, k, v, comp, rag in conn.execute("SELECT site_id, kri, value, comparator, rag FROM ops.kri_values WHERE sim_date = %s", (day,)):
            kri.setdefault(s, {})[k] = {"value": v, "comparator": comp, "rag": rag}
        rows = conn.execute("SELECT site_id, rule_score, model_score FROM ops.site_risk WHERE sim_date = %s ORDER BY rule_score DESC", (day,)).fetchall()
    sites = [{"site_id": s, "name": names.get(s, (None, 0))[0], "subjects": names.get(s, (None, 0))[1], "rule_score": rs, "model_score": ms,
              "kris": kri.get(s, {})} for s, rs, ms in rows if _allowed(caller, s)]
    return {"as_of": str(day), "kri_defs": {k: {"label": d["label"], "rule": d["rule"]} for k, d in KRI_DEFS.items()}, "sites": sites}


@router.get("/visit-plan")
def visit_plan(caller: Annotated[Caller, Depends(get_caller)], month: str | None = None) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        plan = visit_planner.plan(conn, TrialClock(conn).today(), month)
    plan["sites"] = [s for s in plan["sites"] if _allowed(caller, s["site_id"])]
    return plan


@router.get("/{site_id}")
def get_site(site_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    if not _allowed(caller, site_id):
        raise HTTPException(403, "outside your site scope")
    with scoped_connection(caller.role, caller.site_scope) as conn:
        day = _latest(conn)
        row = conn.execute("SELECT rule_score, model_score, signals FROM ops.site_risk WHERE sim_date = %s AND site_id = %s", (day, site_id)).fetchone() if day else None
        if row is None:
            raise HTTPException(404, "no risk data for this site yet")
        name = conn.execute("SELECT name, subjects FROM hub.v_site_summary WHERE site_id = %s", (site_id,)).fetchone()
        history = [{"day": str(d), "rule_score": r} for d, r in conn.execute("SELECT sim_date, rule_score FROM ops.site_risk WHERE site_id = %s ORDER BY sim_date", (site_id,))]
        kris = {k: {"value": v, "comparator": c, "rag": r} for k, v, c, r in conn.execute("SELECT kri, value, comparator, rag FROM ops.kri_values WHERE sim_date = %s AND site_id = %s", (day, site_id))}
        aging = [r for r in aging_by_site(conn, TrialClock(conn).today()) if r["site_id"] == site_id]
        found = site_issues.list_issues(conn, site_id=site_id)
    return {"model": row[2].get("model"), "issues": found, "site_id": site_id, "name": name[0] if name else None, "subjects": name[1] if name else None, "as_of": str(day), "rule_score": row[0],
            "model_score": row[1], "kris": kris, "kri_defs": {k: {"label": d["label"], "rule": d["rule"], "unit": d["unit"]} for k, d in KRI_DEFS.items()},
            "explanations": row[2].get("explanations", []), "anomalies": row[2].get("anomalies", []), "history": history, "open_queries": aging[0] if aging else None}


@router.get("/{site_id}/kris")
def kri_history(site_id: str, caller: Annotated[Caller, Depends(get_caller)], frm: str | None = None, to: str | None = None) -> list[dict]:
    if not _allowed(caller, site_id):
        raise HTTPException(403, "outside your site scope")
    with scoped_connection(caller.role, caller.site_scope) as conn:
        cur = conn.execute("SELECT sim_date::text AS day, kri, value, comparator, rag FROM ops.kri_values WHERE site_id = %s AND (%s::date IS NULL OR sim_date >= %s::date) "
                           "AND (%s::date IS NULL OR sim_date <= %s::date) ORDER BY sim_date, kri", (site_id, frm, frm, to, to))
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/{site_id}/explain")
def explain(site_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> list[dict]:
    return get_site(site_id, caller)["explanations"]


def _draft(site_id: str, kind: str, caller: Caller) -> dict:
    _monitor(caller)
    if not _allowed(caller, site_id):
        raise HTTPException(403, "outside your site scope")
    with get_pool().connection() as conn:       # a draft is a system write; authorization is the role check above
        try:
            return SiteDrafter(conn).draft(site_id, kind, caller.user)
        except LookupError:
            raise HTTPException(404, "no risk data for this site yet")
        except NothingToRaise:
            raise HTTPException(409, "No red or amber indicator at this site, so there is nothing to raise")


@router.post("/{site_id}/agenda")
def draft_agenda(site_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    return _draft(site_id, "agenda", caller)


@router.post("/{site_id}/letter")
def draft_letter(site_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    return _draft(site_id, "letter", caller)


@router.get("/{site_id}/scorecard.pdf")
def scorecard(site_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> Response:
    pdf = scorecard_pdf.render(get_site(site_id, caller))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="site-{site_id}-scorecard.pdf"'})


@issues_router.get("")
def list_issues(caller: Annotated[Caller, Depends(get_caller)], status: str | None = None, site: str | None = None) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return site_issues.list_issues(conn, status, site, caller.site_scope)


@issues_router.patch("/{issue_id}")
def update_issue(issue_id: str, body: IssueIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    _monitor(caller)
    if body.status is not None and body.status not in site_issues.STATUSES:
        raise HTTPException(422, f"status must be one of {', '.join(site_issues.STATUSES)}")
    with get_pool().connection() as conn:
        row = site_issues.update_issue(conn, issue_id, TrialClock(conn).today(), caller.user, body.status, body.owner)
    if row is None:
        raise HTTPException(404, "unknown issue")
    return row
