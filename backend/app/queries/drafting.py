"""Query text. Template fallback now; Gemini drafting arrives in milestone 4 (spec §9.3)."""
from __future__ import annotations

from datetime import date

from psycopg import Connection

from app.queries.drafter import QueryDrafter, template_text  # noqa: F401  (template_text re-exported)
from app.queries.lifecycle import log_drafted
from app.queries.prioritizer import priority, site_rags

SEV_ORDER = "CASE s.severity WHEN 'critical' THEN 0 WHEN 'major' THEN 1 ELSE 2 END"


def draft_new_queries(conn: Connection, day: date, actor: str = "system") -> list[str]:
    """One Draft query per unresolved failure that has none, skipping rows that already have an open query."""
    rags = site_rags(conn, day)
    rows = conn.execute(
        f"SELECT f.id, f.usubjid, f.site_id, f.src_table, f.src_pk, f.observed, f.expected, s.id, s.ctq_category, s.severity, "
        f"       s.params->>'_description', s.type "
        f"FROM ops.check_failures f JOIN ops.check_specs s ON s.id = f.check_id "
        f"WHERE f.resolved_on IS NULL AND f.site_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ops.queries q WHERE q.failure_id = f.id) "
        f"ORDER BY {SEV_ORDER}, f.id").fetchall()
    busy = {(t, p) for t, p in conn.execute(
        "SELECT f.src_table, f.src_pk FROM ops.queries q JOIN ops.check_failures f ON f.id = q.failure_id "
        "WHERE q.state IN ('Draft','Approved','Sent','Answered','Reopened')").fetchall()}
    created: list[str] = []
    drafter = QueryDrafter(conn)
    for fid, usubjid, site, tbl, pk, obs, exp, check_id, ctq, sev, desc, _type in rows:
        if (tbl, pk) in busy:
            continue
        busy.add((tbl, pk))
        failure = dict(check_id=check_id, usubjid=usubjid, site_id=site, src_table=tbl, src_pk=pk, observed=obs, expected=exp)
        drafted = drafter.draft(failure, dict(description=desc or check_id, severity=sev, ctq_category=ctq), day)
        qid = conn.execute(
            "INSERT INTO ops.queries (failure_id, finding_id, site_id, usubjid, priority, state, text, opened_on) "
            "VALUES (%s,%s,%s,%s,%s,'Draft',%s,%s) RETURNING id",
            (fid, drafted.finding_id, site, usubjid, priority(ctq, sev, 0, rags.get(site)), drafted.text, day)).fetchone()[0]
        log_drafted(conn, str(qid), site, day, actor, {"check_id": check_id, "failure_id": fid, "text_source": drafted.source})
        created.append(str(qid))
    return created
