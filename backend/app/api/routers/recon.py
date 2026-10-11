from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.db.connection import scoped_connection
from app.deps import Caller, get_caller
from app.recon.sae.classifier import PairResult, OneSided
from app.recon.sae.reconciler import SaeReconciler
from app.recon.sae.specs import SAE_SPEC_IDS
from app.sim.clock import TrialClock

router = APIRouter(prefix="/recon/sae", tags=["recon"])


def _site_ok(caller: Caller, site: str | None) -> bool:
    return not caller.site_scope or (site is not None and site in caller.site_scope.split(","))


def _pair(p: PairResult, open_items: dict[str, list[dict]]) -> dict:
    m = p.match
    return {"ae_id": m.ae.id, "case_id": m.case.case_id, "version": m.case.version, "usubjid": m.ae.usubjid, "site_id": m.ae.site_id,
            "overall": p.overall, "score": round(m.score, 3), "term_match": {"method": m.term.method, "score": round(m.term.score, 3), "reason": m.term.reason},
            "needs_causality": p.needs_causality,
            "edc": {"term": m.ae.term_coded, "onset": m.ae.onset, "serious": m.ae.serious, "causality": m.ae.causality, "outcome": m.ae.outcome},
            "safety": {"term": m.case.term, "onset": m.case.onset, "serious": m.case.serious == "1", "causality": m.case.causality,
                       "outcome": m.case.outcome, "death": m.case.death == "1", "received": m.case.received},
            "discrepancies": [d.__dict__ for d in p.discrepancies], "open_items": open_items.get(str(m.ae.id), [])}


def _one(o: OneSided) -> dict:
    ae, c = o.ae, o.case
    return {"kind": o.kind, "class": o.cls, "reason": o.reason, "pending": o.pending,
            "ae": None if not ae else {"id": ae.id, "usubjid": ae.usubjid, "site_id": ae.site_id, "term": ae.term_coded, "onset": ae.onset, "outcome": ae.outcome, "entered_at": ae.entered_at},
            "case": None if not c else {"case_id": c.case_id, "version": c.version, "usubjid": c.usubjid, "term": c.term, "onset": c.onset, "outcome": c.outcome,
                                        "site_id": c.usubjid.split("-")[1] if c.usubjid else None}}


def _open_items(conn) -> dict[str, list[dict]]:
    """Unresolved SAE failures with the state of their query, keyed by EDC AE id."""
    rows = conn.execute("SELECT f.src_pk, f.check_id, q.id, q.state FROM ops.check_failures f LEFT JOIN ops.queries q ON q.failure_id = f.id "
                        "WHERE f.check_id = ANY(%s) AND f.src_table = 'edc.ae' AND f.resolved_on IS NULL", (sorted(SAE_SPEC_IDS),)).fetchall()
    out: dict[str, list[dict]] = {}
    for pk, check, qid, state in rows:
        out.setdefault(pk, []).append({"check_id": check, "query_id": str(qid) if qid else None, "query_state": state})
    return out


@router.get("/pairs")
def pairs(caller: Annotated[Caller, Depends(get_caller)], cls: str | None = None, site: str | None = None) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        res = SaeReconciler(conn).compute(TrialClock(conn).today())
        items = _open_items(conn)
    out = [_pair(p, items) for p in res.pairs if (not cls or p.overall == cls) and (not site or p.match.ae.site_id == site) and _site_ok(caller, p.match.ae.site_id)]
    order = {"critical": 0, "actionable": 1, "acceptable": 2, "clean": 3}
    return sorted(out, key=lambda r: (order[r["overall"]], r["usubjid"]))


@router.get("/unmatched")
def unmatched(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        res = SaeReconciler(conn).compute(TrialClock(conn).today())
    items = [_one(o) for o in res.one_sided]
    site = lambda x: (x["ae"] or x["case"])["site_id"]  # noqa: E731
    items = [x for x in items if _site_ok(caller, site(x))]
    return {"edc_only": [x for x in items if x["kind"] == "edc_only" and not x["pending"]],
            "safety_only": [x for x in items if x["kind"] == "safety_only"],
            "pending": [x for x in items if x["pending"]]}


@router.get("/summary")
def summary(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        today = TrialClock(conn).today()
        res = SaeReconciler(conn).compute(today)
        history = [{"day": str(d), **c} for d, c in conn.execute("SELECT sim_date, counts FROM ops.sae_recon_history ORDER BY sim_date")]
        by_field: dict[str, int] = {}
        for p in res.pairs:
            for d in p.discrepancies:
                if d.cls != "acceptable":
                    by_field[d.field] = by_field.get(d.field, 0) + 1
        decisions = conn.execute("SELECT count(*), count(*) FILTER (WHERE same_event) FROM ai.term_decisions").fetchone()
    return {"today": str(today), "counts": res.counts(), "open_by_field": by_field, "history": history,
            "term_decisions": {"total": decisions[0], "same_event": decisions[1]}}


@router.get("/cases/{case_id}/versions")
def versions(case_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        today = TrialClock(conn).today()
        cur = conn.execute("SELECT id, version, received, causality, reaction_term, onset, outcome, serious, death, narrative, available_on "
                           "FROM safety.v_cases WHERE safetyreportid = %s AND available_on <= %s ORDER BY version", (case_id, today))
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    if not rows:
        raise HTTPException(404, "unknown case")
    for prev, cur_ in zip(rows, rows[1:]):
        cur_["changes"] = {k: {"from": prev[k], "to": cur_[k]} for k in ("causality", "reaction_term", "onset", "outcome", "serious", "death") if prev[k] != cur_[k]}
    return {"case_id": case_id, "versions": rows}
