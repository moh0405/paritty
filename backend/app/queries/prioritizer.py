"""priority = w_ctq x w_sev x w_age x w_site (spec §9.3)."""
from __future__ import annotations

from datetime import date

from psycopg import Connection

W_CTQ = {"safety": 1.0, "efficacy": 0.8, "eligibility": 0.7, "other": 0.3}
W_SEV = {"critical": 1.0, "major": 0.6, "minor": 0.2}
W_SITE = {"red": 1.5, "amber": 1.2}


def age_weight(days_open: int) -> float:
    return min(3.0, 1.0 + max(0, days_open) / 14)


def priority(ctq: str, severity: str, days_open: int, site_rag: str | None = None) -> float:
    return round(W_CTQ[ctq] * W_SEV[severity] * age_weight(days_open) * W_SITE.get(site_rag or "", 1.0), 4)


def site_rags(conn: Connection, day: date) -> dict[str, str]:
    """Worst KRI status per site on the latest KRI day at or before `day` (empty until KRIs exist, milestone 7)."""
    rows = conn.execute(
        "SELECT site_id, CASE WHEN bool_or(rag='red') THEN 'red' WHEN bool_or(rag='amber') THEN 'amber' ELSE 'green' END "
        "FROM ops.kri_values WHERE sim_date = (SELECT max(sim_date) FROM ops.kri_values WHERE sim_date <= %s) GROUP BY site_id",
        (day,)).fetchall()
    return dict(rows)


def reprioritize_open(conn: Connection, day: date) -> int:
    rags = site_rags(conn, day)
    rows = conn.execute(
        "SELECT q.id, s.ctq_category, s.severity, q.opened_on, q.site_id FROM ops.queries q "
        "JOIN ops.check_failures f ON f.id = q.failure_id JOIN ops.check_specs s ON s.id = f.check_id "
        "WHERE q.state IN ('Draft','Approved','Sent','Answered','Reopened')").fetchall()
    for qid, ctq, sev, opened, site in rows:
        conn.execute("UPDATE ops.queries SET priority = %s WHERE id = %s",
                     (priority(ctq, sev, (day - opened).days, rags.get(site)), qid))
    return len(rows)
