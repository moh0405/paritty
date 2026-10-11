from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.connection import scoped_connection
from app.deps import Caller, get_caller
from app.domain.enums import Role
from app.queries import lifecycle as lc
from app.queries.aging import BUCKETS, aging_by_site
from app.sim.clock import TrialClock

router = APIRouter(prefix="/queries", tags=["queries"])


class CloseIn(BaseModel):
    reason: str


class PatchIn(BaseModel):
    text: str
    language: str | None = None


class TranslateIn(BaseModel):
    language: str


def _rows(cur) -> list[dict]:
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _require_dm(caller: Caller) -> None:
    if caller.role is not Role.DATA_MANAGER:
        raise HTTPException(403, "Only a data manager can change queries")


@router.get("")
def list_queries(caller: Annotated[Caller, Depends(get_caller)], state: str | None = None, site: str | None = None,
                 min_priority: float | None = None, limit: int = 300) -> list[dict]:
    where, params = ["true"], {"limit": min(limit, 1000)}
    if state:
        where.append("q.state = %(state)s")
        params["state"] = state
    if site:
        where.append("q.site_id = %(site)s")
        params["site"] = site
    if min_priority is not None:
        where.append("q.priority >= %(mp)s")
        params["mp"] = min_priority
    if caller.site_scope:
        where.append("q.site_id = ANY(string_to_array(%(scope)s, ','))")
        params["scope"] = caller.site_scope
    with scoped_connection(caller.role, caller.site_scope) as conn:
        today = TrialClock(conn).today()
        rows = _rows(conn.execute(
            f"SELECT q.*, f.check_id, s.params->>'_description' AS check_description, s.ctq_category, s.severity, "
            f"(%(today)s::date - q.opened_on) AS age_days, f.src_table, f.src_pk, "
            f"fi.verification_status, fi.body->>'source' AS text_source "
            f"FROM ops.queries q JOIN ops.check_failures f ON f.id = q.failure_id JOIN ops.check_specs s ON s.id = f.check_id "
            f"LEFT JOIN ai.findings fi ON fi.id = q.finding_id "
            f"WHERE {' AND '.join(where)} ORDER BY q.priority DESC, q.opened_on LIMIT %(limit)s", {**params, "today": today}))
    return rows


@router.get("/aging")
def aging(caller: Annotated[Caller, Depends(get_caller)], by: str = "site") -> dict:
    if by != "site":
        raise HTTPException(400, "only by=site is supported")
    with scoped_connection(caller.role, caller.site_scope) as conn:
        rows = aging_by_site(conn, TrialClock(conn).today())
    if caller.site_scope:
        allowed = set(caller.site_scope.split(","))
        rows = [r for r in rows if r["site_id"] in allowed]
    return {"buckets": BUCKETS, "rows": rows}


@router.get("/stats")
def stats(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        by_state = dict(conn.execute("SELECT state, count(*) FROM ops.queries GROUP BY 1").fetchall())
        daily = _rows(conn.execute(
            "SELECT sim_date::text AS day, count(*) FILTER (WHERE event='opened') AS opened, count(*) FILTER (WHERE event='closed' "
            "OR event='closed_with_explanation') AS closed, count(*) FILTER (WHERE event='reopened') AS reopened "
            "FROM ops.query_events GROUP BY sim_date ORDER BY sim_date"))
    return {"by_state": by_state, "daily": daily}


@router.get("/{query_id}")
def get_query(query_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        q = _rows(conn.execute(
            "SELECT q.*, f.check_id, f.src_table, f.src_pk, f.observed, f.expected, s.params->>'_description' AS check_description, "
            "s.ctq_category, s.severity FROM ops.queries q JOIN ops.check_failures f ON f.id = q.failure_id "
            "JOIN ops.check_specs s ON s.id = f.check_id WHERE q.id = %s", (query_id,)))
        if not q:
            raise HTTPException(404, "unknown query")
        events = _rows(conn.execute("SELECT sim_date::text, event, actor, detail FROM ops.query_events WHERE query_id = %s ORDER BY ts, event", (query_id,)))
    return {**q[0], "events": events}


def _act(caller: Caller, query_id: str, action: str, set_cols: dict | None = None) -> dict:
    _require_dm(caller)
    with scoped_connection(caller.role, caller.site_scope) as conn:
        try:
            nxt = lc.transition(lc.Ctx(conn, query_id, TrialClock(conn).today(), caller.user), action, set_cols)
        except KeyError:
            raise HTTPException(404, "unknown query")
        except lc.IllegalTransition as exc:
            raise HTTPException(409, str(exc))
    return {"id": query_id, "state": nxt}


@router.post("/{query_id}/approve")
def approve(query_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    return _act(caller, query_id, "approve")


@router.post("/{query_id}/close")
def close(query_id: str, body: CloseIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    action = "close_with_explanation" if (_state(caller, query_id) == lc.ANSWERED and body.reason.strip()) else "close"
    return _act(caller, query_id, action, {"closed_reason": body.reason})


def _state(caller: Caller, query_id: str) -> str | None:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        r = conn.execute("SELECT state FROM ops.queries WHERE id = %s", (query_id,)).fetchone()
    return r[0] if r else None


@router.patch("/{query_id}")
def patch(query_id: str, body: PatchIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    _require_dm(caller)
    with scoped_connection(caller.role, caller.site_scope) as conn:
        n = conn.execute("UPDATE ops.queries SET text = %s, language = COALESCE(%s, language) WHERE id = %s AND state = 'Draft'", (body.text, body.language, query_id)).rowcount
        if not n:
            raise HTTPException(409, "only Draft queries can be edited")
    return {"id": query_id, "state": "Draft"}


@router.post("/{query_id}/translate")
def translate(query_id: str, body: TranslateIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    """Translate a query for a site that works in another language. The result is blocked if any number, date or identifier changes.
    Nothing is saved: a person reviews it and saves it with PATCH (language included)."""
    from app.queries.translate import LANGUAGES, QueryTranslator, TranslationBlocked, TranslationUnavailable
    _require_dm(caller)
    if body.language not in LANGUAGES:
        raise HTTPException(422, f"language must be one of {', '.join(LANGUAGES)}")
    with scoped_connection(caller.role, caller.site_scope) as conn:
        row = conn.execute("SELECT text FROM ops.queries WHERE id = %s", (query_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "unknown query")
    try:
        out = QueryTranslator().translate(row[0], body.language)
    except TranslationBlocked as exc:
        raise HTTPException(422, "Translation blocked: " + "; ".join(exc.issues))
    except TranslationUnavailable as exc:
        raise HTTPException(503, str(exc))
    return {"id": query_id, "language": out.language, "text": out.text, "source_text": out.source_text}
