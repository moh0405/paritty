"""CheckEffectiveness (spec §9.2): which checks earn their keep. In-app view uses what reviewers decided; the eval view compares with the planted truth."""
from __future__ import annotations

from psycopg import Connection

RETIRE_MIN_DECISIONS = 5
RETIRE_DISMISS_RATE = 0.5


def in_app(conn: Connection) -> list[dict]:
    """Confirmed = the query ended with a correction; dismissed = the site explained the value was right. A high dismissed share suggests a false-alarm-prone check."""
    rows = conn.execute(
        "SELECT s.id, s.params->>'_description', s.source, s.approval_status, count(f.id), count(f.id) FILTER (WHERE f.resolved_on IS NULL), "
        "count(q.id) FILTER (WHERE q.state = 'Closed'), count(q.id) FILTER (WHERE q.state = 'ClosedWithExplanation') "
        "FROM ops.check_specs s LEFT JOIN ops.check_failures f ON f.check_id = s.id LEFT JOIN ops.queries q ON q.failure_id = f.id GROUP BY s.id ORDER BY s.id").fetchall()
    out = []
    for cid, desc, source, appr, total, open_, confirmed, dismissed in rows:
        decided = confirmed + dismissed
        rate = dismissed / decided if decided else None
        out.append({"check_id": cid, "description": desc, "source": source, "approval_status": appr, "failures": total, "open": open_,
                    "confirmed": confirmed, "dismissed": dismissed, "dismissed_rate": rate,
                    "recommend_retire": bool(decided >= RETIRE_MIN_DECISIONS and rate is not None and rate > RETIRE_DISMISS_RATE)})
    return out


def eval_scores(eval_conn: Connection) -> list[dict]:
    """Per check, failures on planted rows (true positives) versus the rest. Run as eval_admin; the app never calls this."""
    planted = {(t, str(k)) for t, k in eval_conn.execute("SELECT src_table, src_pk FROM answer_key.planted WHERE module = 'checks' AND src_pk IS NOT NULL")}
    by: dict[str, list[int]] = {}
    for cid, t, k in eval_conn.execute("SELECT check_id, src_table, src_pk FROM ops.check_failures"):
        tp = (t, str(k)) in planted
        by.setdefault(cid, [0, 0])[0 if tp else 1] += 1
    return [{"check_id": c, "true_positives": tp, "other": o, "precision_on_planted": tp / (tp + o) if tp + o else None} for c, (tp, o) in sorted(by.items())]
