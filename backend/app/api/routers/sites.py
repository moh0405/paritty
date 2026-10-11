from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.db.connection import scoped_connection
from app.deps import Caller, get_caller
from app.queries.aging import aging_by_site
from app.sim.clock import TrialClock
from app.sites.kris import KRI_DEFS

router = APIRouter(prefix="/sites", tags=["sites"])


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
    return {"site_id": site_id, "name": name[0] if name else None, "subjects": name[1] if name else None, "as_of": str(day), "rule_score": row[0],
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
