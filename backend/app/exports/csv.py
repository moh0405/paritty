"""CSV exports (spec §9.12): queries, findings and reconciliation items, under the caller's role and site scope."""
from __future__ import annotations

import csv
import io

from psycopg import Connection

SQL = {
    "queries": ("SELECT q.id, q.site_id, q.usubjid, q.state, q.priority, f.check_id, s.severity, q.opened_on, q.sent_on, q.answered_on, q.closed_on, q.reopen_count, q.closed_reason, q.text "
                "FROM ops.queries q JOIN ops.check_failures f ON f.id = q.failure_id JOIN ops.check_specs s ON s.id = f.check_id WHERE {scope} ORDER BY q.priority DESC, q.opened_on", "q.site_id"),
    "findings": ("SELECT id, module, rule_id, severity, usubjid, site_id, title, verification_status, review_status, sim_date FROM ai.findings "
                 "WHERE verification_status <> 'blocked' AND {scope} ORDER BY created_at DESC", "site_id"),
    "recon": ("SELECT f.check_id, f.usubjid, f.site_id, f.observed, f.expected, f.detected_on, f.resolved_on FROM ops.check_failures f "
              "WHERE (f.check_id LIKE 'sae\\_%%' OR f.check_id IN ('chk_22','chk_24','chk_25','chk_26','lab_stale_feed')) AND {scope} ORDER BY f.detected_on DESC", "f.site_id"),
}


def export(conn: Connection, name: str, site_scope: str | None) -> str:
    sql, site_col = SQL[name]
    scope, params = ("true", ()) if not site_scope else (f"{site_col} = ANY(string_to_array(%s, ','))", (site_scope,))
    cur = conn.execute(sql.format(scope=scope), params)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([d.name for d in cur.description])
    for row in cur.fetchall():
        w.writerow(["" if v is None else v for v in row])
    return out.getvalue()
