from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.audit.logger import audit
from app.db.connection import get_pool, scoped_connection
from app.deps import Caller, get_caller
from app.domain.enums import Role
from app.hub import catalog, dq, lineage, questions
from app.sim.clock import TrialClock

router = APIRouter(tags=["hub"])


class ConfirmIn(BaseModel):
    canonical: str | None = None      # required to resolve an unmatched identifier


def _today():
    """The simulated date comes from the system connection: not every role may read ops.sim_clock."""
    with get_pool().connection() as c:
        return TrialClock(c).today()


def _rows(cur) -> list[dict]:
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/hub/catalog")
def get_catalog(caller: Annotated[Caller, Depends(get_caller)], q: str | None = None) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return catalog.search(conn, q, _today())


@router.get("/hub/xwalk")
def get_xwalk(caller: Annotated[Caller, Depends(get_caller)], entity: str = "subject", status: str | None = None, system: str | None = None, limit: int = 300) -> list[dict]:
    table, col = ("hub.site_xwalk", "canonical_site") if entity == "site" else ("hub.subject_xwalk", "canonical_subject")
    where, params = ["true"], {"limit": min(limit, 1000)}
    for c, v in (("status", status), ("system", system)):
        if v:
            where.append(f"{c} = %({c})s")
            params[c] = v
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return _rows(conn.execute(f"SELECT system, source_id, {col} AS canonical, confidence, method, status, confirmed_by FROM {table} WHERE {' AND '.join(where)} "
                                  f"ORDER BY (status = 'unmatched') DESC, (status = 'proposed') DESC, confidence, source_id LIMIT %(limit)s", params))


def _review(caller: Caller, system: str, source_id: str, new_status: str, canonical: str | None) -> dict:
    if caller.role not in (Role.DATA_MANAGER, Role.CENTRAL_MONITOR):
        raise HTTPException(403, "Only a data manager or central monitor can review mappings")
    with scoped_connection(caller.role, caller.site_scope) as conn:
        site = system == "ctms"
        table, col = ("hub.site_xwalk", "canonical_site") if site else ("hub.subject_xwalk", "canonical_subject")
        row = conn.execute(f"SELECT {col}, status FROM {table} WHERE system = %s AND source_id = %s", (system, source_id)).fetchone()
        if row is None:
            raise HTTPException(404, "unknown mapping")
        target = canonical or row[0]
        if new_status == "confirmed":
            if not target:
                raise HTTPException(422, "choose the subject or site this identifier belongs to")
            exists = conn.execute("SELECT 1 FROM edc.sites WHERE site_id = %s" if site else "SELECT 1 FROM edc.subjects WHERE usubjid = %s", (target,)).fetchone()
            if not exists:
                raise HTTPException(422, f"{target} is not a known {'site' if site else 'subject'}")
        conn.execute(f"UPDATE {table} SET {col} = %s, status = %s, confirmed_by = %s, confidence = CASE WHEN %s THEN 1 ELSE confidence END, method = CASE WHEN %s THEN 'manual' ELSE method END "
                     f"WHERE system = %s AND source_id = %s", (target if new_status == "confirmed" else row[0], new_status, caller.user, new_status == "confirmed" and canonical is not None,
                                                             new_status == "confirmed" and canonical is not None, system, source_id))
        audit(conn, TrialClock(conn).today(), caller.user, f"xwalk.{new_status}", "xwalk", f"{system}:{source_id}", {"canonical": target}, role=caller.role.value)
    return {"system": system, "source_id": source_id, "status": new_status, "canonical": target}


@router.post("/hub/xwalk/{system}/{source_id:path}/confirm")
def confirm(system: str, source_id: str, body: ConfirmIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    return _review(caller, system, source_id, "confirmed", body.canonical)


@router.post("/hub/xwalk/{system}/{source_id:path}/reject")
def reject(system: str, source_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    return _review(caller, system, source_id, "rejected", None)


@router.get("/hub/dq")
def get_dq(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        rules = dq.latest(conn)
        fresh = catalog.search(conn, None, _today(), limit=100)
    return {"dimensions": dq.DIMENSIONS, "rules": rules,
            "freshness": [{"table": t["table_name"], "age_days": t["age_days"], "refresh": t["refresh"]} for t in fresh if t["age_days"] is not None and t["table_name"] in catalog.FRESHNESS]}


@router.get("/hub/questions")
def list_questions() -> list[dict]:
    return questions.catalog()


@router.get("/hub/questions/{n}")
def run_question(n: int, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        try:
            out = questions.run(conn, n)
        except KeyError:
            raise HTTPException(404, "unknown question")
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
    with get_pool().connection() as sysconn:      # the clock and the audit log are system data: the caller role (e.g. study lead) may not read or write them
        audit(sysconn, TrialClock(sysconn).today(), caller.user, "hub.question", "question", str(n), {"level": out["level"], "rows": len(out["rows"])}, role=caller.role.value)
    return {**out, "role": caller.role.value, "site_scope": caller.site_scope}


@router.get("/lineage/{entity}/{entity_id}")
def get_lineage(entity: str, entity_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    if entity not in ("failure", "query", "finding"):
        raise HTTPException(404, "lineage is available for failure, query and finding")
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return lineage.trail(conn, entity, entity_id)


class AskIn(BaseModel):
    question: str


@router.post("/hub/ask")
def ask(body: AskIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    """Natural-language question -> guarded read-only SQL under the caller's role, with lineage (spec §9.9)."""
    from app.hub.ask import AskService, GuardError, Unanswerable
    today = _today()
    with scoped_connection(caller.role, caller.site_scope) as conn:
        try:
            out = AskService(conn, schema_conn=conn).ask(body.question.strip())
        except Unanswerable as exc:
            raise HTTPException(422, str(exc))
        except GuardError as exc:
            raise HTTPException(422, f"That query was not run: {exc}")
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
    with get_pool().connection() as sysconn:
        audit(sysconn, today, caller.user, "hub.ask", "question", None, {"sql": out.sql[:500], "rows": len(out.rows), "source": out.source}, role=caller.role.value)
    return {"question": out.question, "sql": out.sql, "explanation": out.explanation, "columns": out.columns, "rows": out.rows, "level": out.level, "note": out.note,
            "source": out.source, "lineage": {"sql": out.sql, "tables": out.tables}, "role": caller.role.value}
