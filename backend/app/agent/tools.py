"""Tools for the data-manager agent (spec §9.11): list blockers, summarise a site, estimate an action's impact, draft an action."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from statistics import mean

from psycopg import Connection

from app.forecast.service import ForecastService, Hypothetical

ACTIONS = {
    "schedule_call": {"factor": 0.7, "label": "Schedule a call with the site", "phrase": "scheduling a call with the site"},
    "escalate_site": {"factor": 0.5, "label": "Escalate the site to the study lead", "phrase": "escalating the site to the study lead"},
}
MIN_GAIN_DAYS = 0.5
REPEAT_WINDOW_DAYS = 14


@dataclass
class Candidate:
    id: str
    kind: str
    site_id: str
    label: str
    factor: float
    current_days: float
    target_days: float
    open_queries: int
    est_delta_p50_days: float
    detail: dict = field(default_factory=dict)

    def numbers(self) -> set[float]:
        site = float(self.site_id) if self.site_id.isdigit() else -1.0
        return {site, round(self.current_days), round(self.target_days), round(self.est_delta_p50_days), float(self.open_queries), round(self.factor * 100), round((1 - self.factor) * 100)}


class AgentTools:
    def __init__(self, conn: Connection, n_sims: int = 600):
        self.conn, self.svc = conn, ForecastService(conn, n_sims)

    def list_blockers(self, day: date) -> list[dict]:
        return [b for b in self.svc.run(day)["blockers"] if b["type"] == "site"]

    def site_response_days(self, site: str) -> float:
        rows = self.conn.execute("SELECT closed_on - opened_on FROM ops.queries WHERE site_id = %s AND state IN ('Closed','ClosedWithExplanation') AND closed_on IS NOT NULL", (site,)).fetchall()
        if len(rows) >= 3:
            return float(mean(r[0] for r in rows))
        pooled = self.conn.execute("SELECT avg(closed_on - opened_on) FROM ops.queries WHERE state IN ('Closed','ClosedWithExplanation') AND closed_on IS NOT NULL").fetchone()[0]
        return float(pooled) if pooled else 8.0

    def get_site_summary(self, site: str, day: date) -> dict:
        r = self.conn.execute("SELECT open_queries, open_critical_queries, open_sae_discrepancies FROM hub.v_open_items WHERE site_id = %s", (site,)).fetchone() or (0, 0, 0)
        score = self.conn.execute("SELECT rule_score FROM ops.site_risk WHERE site_id = %s ORDER BY sim_date DESC LIMIT 1", (site,)).fetchone()
        return {"site_id": site, "open_queries": r[0], "open_critical": r[1], "open_sae": r[2], "risk_score": float(score[0]) if score else None, "response_days": round(self.site_response_days(site), 1)}

    def estimate_impact(self, day: date, baseline_p50: date, site: str, target_days: float) -> float:
        """How many days earlier the most likely lock date would be if this site answered in about `target_days`."""
        alt = self.svc.run(day, Hypothetical(site_response_days={site: max(0.5, target_days)}))
        return float((baseline_p50 - alt["p50"]).days)

    def candidates(self, day: date, limit_sites: int = 6) -> list[Candidate]:
        base = self.svc.run(day)
        out: list[Candidate] = []
        for b in [x for x in base["blockers"] if x["type"] == "site"][:limit_sites]:
            site = b["id"]
            cur = self.site_response_days(site)
            s = self.get_site_summary(site, day)
            for kind, spec in ACTIONS.items():
                target = max(1.0, cur * spec["factor"])
                out.append(Candidate(f"{kind}:{site}", kind, site, spec["label"], spec["factor"], cur, target, int(s["open_queries"]),
                                     self.estimate_impact(day, base["p50"], site, target), {"blocker_delta_p50_days": b["delta_p50_days"], "summary": s}))
        return out

    def recently_proposed(self, site: str, kind: str, day: date) -> bool:
        return bool(self.conn.execute(
            "SELECT 1 FROM ops.drafts WHERE kind = 'agent_action' AND site_id = %s AND body->>'action' = %s AND state <> 'rejected' AND (body->>'sim_date')::date > %s LIMIT 1",
            (site, kind, day - __import__("datetime").timedelta(days=REPEAT_WINDOW_DAYS))).fetchone())

    def draft_action(self, c: Candidate, rationale: str, source: str, day: date) -> str:
        body = {"action": c.kind, "site_id": c.site_id, "label": c.label, "factor": c.factor, "current_response_days": round(c.current_days, 1), "target_response_days": round(c.target_days, 1),
                "est_delta_p50_days": c.est_delta_p50_days, "open_queries": c.open_queries, "text": rationale, "source": source, "sim_date": str(day), "verification_status": "verified"}
        return str(self.conn.execute("INSERT INTO ops.drafts (kind, subject_ref, site_id, body, state) VALUES ('agent_action', NULL, %s, %s, 'draft') RETURNING id",
                                     (c.site_id, json.dumps(body))).fetchone()[0])
