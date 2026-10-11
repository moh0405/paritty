from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.audit.logger import audit
from app.db.connection import scoped_connection
from app.deps import Caller, get_caller
from app.sim.clock import TrialClock
from app.verification.normalize import norm_cell
from app.verification.sources import fetch_row

router = APIRouter(tags=["findings"])


class ReviewIn(BaseModel):
    review_status: Literal["open", "confirmed", "dismissed"]
    reviewer_note: str | None = None


def _rows(cur) -> list[dict]:
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/findings")
def list_findings(caller: Annotated[Caller, Depends(get_caller)], module: str | None = None, status: str | None = None,
                  site: str | None = None, usubjid: str | None = None, include_blocked: bool = False, limit: int = 200) -> list[dict]:
    where, params = ["true"], {"limit": min(limit, 1000)}
    for col, val in (("module", module), ("verification_status", status), ("site_id", site), ("usubjid", usubjid)):
        if val:
            where.append(f"{col} = %({col})s")
            params[col] = val
    if not include_blocked and not status:
        where.append("verification_status <> 'blocked'")      # blocked items are stored but hidden from review queues
    if caller.site_scope:
        where.append("site_id = ANY(string_to_array(%(scope)s, ','))")
        params["scope"] = caller.site_scope
    with scoped_connection(caller.role, caller.site_scope) as conn:
        return _rows(conn.execute(
            f"SELECT id, module, rule_id, severity, usubjid, site_id, title, verification_status, review_status, sim_date, "
            f"jsonb_array_length(body->'claims') AS claims FROM ai.findings WHERE {' AND '.join(where)} "
            f"ORDER BY created_at DESC, id LIMIT %(limit)s", params))


@router.get("/findings/stats")
def stats(caller: Annotated[Caller, Depends(get_caller)], module: str | None = None) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        by_status = dict(conn.execute("SELECT verification_status, count(*) FROM ai.findings WHERE (%(m)s::text IS NULL OR module = %(m)s) "
                                      "GROUP BY 1", {"m": module}).fetchall())
        claims = dict(conn.execute(
            "SELECT c->>'status', count(*) FROM ai.findings f, jsonb_array_elements(f.body->'claims') c "
            "WHERE (%(m)s::text IS NULL OR f.module = %(m)s) GROUP BY 1", {"m": module}).fetchall())
        llm = conn.execute("SELECT count(*), count(*) FILTER (WHERE cache_hit), coalesce(sum(input_tokens),0), coalesce(sum(output_tokens),0), "
                           "coalesce(avg(latency_ms) FILTER (WHERE NOT cache_hit),0) FROM ai.llm_calls").fetchone()
    total = sum(claims.values())
    return {"findings_by_status": by_status, "claims_by_status": claims, "grounding_rate": (claims.get("verified", 0) / total) if total else None,
            "blocked_claims": total - claims.get("verified", 0), "llm_calls": {"total": llm[0], "cache_hits": llm[1], "input_tokens": int(llm[2]),
                                                                              "output_tokens": int(llm[3]), "avg_latency_ms": round(float(llm[4]))}}


@router.get("/findings/{finding_id}")
def get_finding(finding_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        f = _rows(conn.execute("SELECT * FROM ai.findings WHERE id = %s", (finding_id,)))
        if not f:
            raise HTTPException(404, "unknown finding")
        cites = _rows(conn.execute("SELECT id, claim_idx, src_table AS table, src_pk AS pk, src_column AS column, cited_value AS value, quote "
                                   "FROM ai.citations WHERE finding_id = %s ORDER BY id", (finding_id,)))
        checks = _rows(conn.execute("SELECT claim_idx, check_name AS name, passed, detail FROM ai.verifications WHERE finding_id = %s ORDER BY id", (finding_id,)))
    finding = f[0]
    claims = []
    for i, c in enumerate(finding["body"].get("claims", [])):
        claims.append({"idx": i, "text": c["text"], "status": c["status"],
                       "citations": [x for x in cites if x["claim_idx"] == i], "checks": [x for x in checks if x["claim_idx"] == i]})
    body = {k: v for k, v in finding["body"].items() if k != "claims"}
    return {**{k: finding[k] for k in ("id", "module", "rule_id", "severity", "usubjid", "site_id", "title", "verification_status",
                                       "review_status", "reviewer_note", "sim_date")}, "claims": claims, "detail": body}


@router.patch("/findings/{finding_id}")
def review(finding_id: str, body: ReviewIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        n = conn.execute("UPDATE ai.findings SET review_status = %s, reviewer_note = %s WHERE id = %s",
                         (body.review_status, body.reviewer_note, finding_id)).rowcount
        if not n:
            raise HTTPException(404, "unknown finding")
        audit(conn, TrialClock(conn).today(), caller.user, "finding.reviewed", "finding", finding_id,
              {"review_status": body.review_status}, role=caller.role.value)
    return {"id": finding_id, "review_status": body.review_status}


@router.get("/citations/{citation_id}/source")
def citation_source(citation_id: int, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    """The cited row as the caller's role sees it, with the cited cell and whether it still matches."""
    with scoped_connection(caller.role, caller.site_scope) as conn:
        c = _rows(conn.execute("SELECT src_table, src_pk, src_column, cited_value, quote FROM ai.citations WHERE id = %s", (citation_id,)))
        if not c:
            raise HTTPException(404, "unknown citation")
        c = c[0]
        row = fetch_row(conn, c["src_table"], c["src_pk"])
    if row is None:
        raise HTTPException(403, "Your role can't see this row, or it no longer exists.")
    cell = row.get(c["src_column"])
    return {"table": c["src_table"], "pk": c["src_pk"], "column": c["src_column"], "cited_value": c["cited_value"], "quote": c["quote"],
            "row": row, "cell": cell, "matches": norm_cell(cell) == norm_cell(c["cited_value"])}
