"""Monitoring plan (spec §9.7): rank sites by risk x enrolled subjects and propose a visit, a call or a remote review."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

from psycopg import Connection

RED_SIGNALS_FOR_VISIT = 2      # two or more red indicators: go on site
AMBER_SIGNALS_FOR_CALL = 2     # one red, or two or more amber: call
ACTIONS = {"red": "visit", "amber": "call"}


def site_level(reds: int, ambers: int) -> str:
    if reds >= RED_SIGNALS_FOR_VISIT:
        return "red"
    return "amber" if reds >= 1 or ambers >= AMBER_SIGNALS_FOR_CALL else "green"


def action_for(level: str, open_issues: int) -> str | None:
    """visit (red), call (amber), remote review (green with open issues); a quiet green site needs nothing this month."""
    return ACTIONS.get(level) or ("remote" if open_issues > 0 else None)


def risk_of(rule_score: float, model_score: float | None) -> float:
    """0-1. The two scores are averaged when the model is available, so neither alone decides the ranking."""
    return (rule_score if model_score is None else (rule_score + model_score) / 2) / 100


def next_month(today: date) -> str:
    return f"{today.year + (today.month == 12)}-{today.month % 12 + 1:02d}"


@dataclass
class PlanRow:
    site_id: str
    name: str | None
    subjects: int
    rule_score: float
    model_score: float | None
    level: str
    action: str
    priority: float
    reds: int
    ambers: int
    open_issues: int
    last_monitoring_visit: str | None
    days_since_visit: int | None
    reasons: list[str]


def plan(conn: Connection, today: date, month: str | None = None) -> dict:
    day = conn.execute("SELECT max(sim_date) FROM ops.site_risk").fetchone()[0]
    if day is None:
        return {"as_of": None, "month": month or next_month(today), "sites": []}
    rag: dict[str, dict[str, int]] = {}
    for site, level, n in conn.execute("SELECT site_id, rag, count(*) FROM ops.kri_values WHERE sim_date = %s AND rag IN ('red','amber') GROUP BY 1, 2", (day,)):
        rag.setdefault(site, {})[level] = n
    issues = dict(conn.execute("SELECT site_id, count(*) FROM ops.issues WHERE status <> 'closed' GROUP BY 1").fetchall())
    last = dict(conn.execute("SELECT site_id, last_monitoring_visit FROM hub.v_site_monitoring").fetchall())
    rows: list[PlanRow] = []
    for site, name, subjects, rule, model, signals in conn.execute(
            "SELECT r.site_id, s.name, s.subjects, r.rule_score, r.model_score, r.signals FROM ops.site_risk r "
            "JOIN hub.v_site_summary s USING (site_id) WHERE r.sim_date = %s", (day,)):
        flagged = sum(1 for a in signals.get("anomalies", []) if a["flagged"])
        reds, ambers = rag.get(site, {}).get("red", 0) + flagged, rag.get(site, {}).get("amber", 0)
        level = site_level(reds, ambers)
        action = action_for(level, issues.get(site, 0))
        if action is None:
            continue
        seen = last.get(site)
        rows.append(PlanRow(site, name, subjects, rule, model, level, action, round(risk_of(rule, model) * subjects, 2), reds, ambers, issues.get(site, 0),
                            str(seen) if seen else None, (today - seen).days if seen else None, [e["text"] for e in signals.get("explanations", [])]))
    rows.sort(key=lambda r: (-r.priority, r.site_id))
    return {"as_of": str(day), "month": month or next_month(today), "sites": [asdict(r) for r in rows]}
