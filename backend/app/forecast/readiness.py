"""Lock-readiness checklist (spec §9.8)."""
from __future__ import annotations

from datetime import date

from psycopg import Connection

from app.sim.schedule import SCHEDULE


def criteria(conn: Connection, today: date) -> list[dict]:
    q = lambda sql, *p: conn.execute(sql, p).fetchone()[0]  # noqa: E731
    not_final = q("SELECT count(*) FROM edc.subjects WHERE status = 'enrolled'")
    missing_visits = q("SELECT count(*) FROM ops.check_failures WHERE check_id = 'chk_17' AND resolved_on IS NULL")
    open_major = q("SELECT count(*) FROM ops.queries q JOIN ops.check_failures f ON f.id = q.failure_id JOIN ops.check_specs s ON s.id = f.check_id "
                   "WHERE q.state IN ('Draft','Approved','Sent','Answered','Reopened') AND s.severity IN ('critical','major')")
    sae_open = q("SELECT coalesce((SELECT (counts->>'open_discrepancies')::int FROM ops.sae_recon_history WHERE sim_date = (SELECT max(sim_date) FROM ops.sae_recon_history)), 0)")
    lab_open = q("SELECT count(*) FROM ops.check_failures WHERE check_id IN ('chk_24','chk_25','chk_26') AND resolved_on IS NULL")
    flagged = {u for (u,) in conn.execute("SELECT DISTINCT usubjid FROM ai.findings WHERE module = 'medical' AND usubjid IS NOT NULL AND severity IN ('critical','high')")}
    signed = {u for (u,) in conn.execute("SELECT DISTINCT subject_ref FROM ops.drafts WHERE kind = 'note' AND state IN ('signed','approved') AND subject_ref IS NOT NULL")}
    undecided_checks = q("SELECT count(*) FROM ops.check_specs WHERE approval_status = 'pending_approval'")
    return [
        {"key": "subjects_final", "label": "All subjects have a final status", "remaining": not_final, "met": not_final == 0,
         "detail": f"{not_final} subjects are still in the study"},
        {"key": "visits_entered", "label": "All expected visits are entered", "remaining": missing_visits, "met": missing_visits == 0 and not_final == 0,
         "detail": f"{missing_visits} overdue visits are not entered; visits for ongoing subjects are still to come"},
        {"key": "queries", "label": "No open critical or major queries", "remaining": open_major, "met": open_major == 0, "detail": f"{open_major} open"},
        {"key": "sae_recon", "label": "Serious adverse events are reconciled", "remaining": sae_open, "met": sae_open == 0, "detail": f"{sae_open} open discrepancies"},
        {"key": "lab_recon", "label": "Central lab data are reconciled", "remaining": lab_open, "met": lab_open == 0, "detail": f"{lab_open} open lab differences"},
        {"key": "notes", "label": "Medical review notes are signed for flagged patients", "remaining": len(flagged - signed), "met": not (flagged - signed),
         "detail": f"{len(flagged - signed)} of {len(flagged)} flagged patients have no signed note"},
        {"key": "generated_checks", "label": "Generated edit checks are approved or rejected", "remaining": undecided_checks, "met": undecided_checks == 0,
         "detail": f"{undecided_checks} awaiting a decision"},
    ]
