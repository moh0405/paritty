from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.db.connection import scoped_connection
from app.deps import Caller, get_caller

router = APIRouter(tags=["checks"])


def _rows(cur) -> list[dict]:
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/checks")
def list_checks(caller: Annotated[Caller, Depends(get_caller)]) -> list[dict]:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return _rows(conn.execute(
            "SELECT s.id, s.type, s.params->>'_description' AS description, s.ctq_category, s.severity, s.source, "
            "s.approval_status, s.active, count(f.id) AS failures, count(f.id) FILTER (WHERE f.resolved_on IS NULL) AS open_failures "
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
