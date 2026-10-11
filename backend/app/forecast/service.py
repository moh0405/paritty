"""ForecastService: builds the work items from live data, runs the Monte Carlo, and stores the daily forecast (spec §9.8)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median

import numpy as np
from psycopg import Connection

from app.forecast import readiness
from app.forecast.montecarlo import Items, KmSampler, MixtureSampler, blockers, percentiles, simulate
from app.sim.schedule import SCHEDULE

PLANNED_ENROLLMENT = 400            # protocol §1: "approximately 400 subjects"
FOLLOWUP_DAYS = 182 + 14            # Week 26 after baseline, baseline about two weeks after consent
TUFTS_DAYS = 36                     # benchmark: last patient last visit to database lock
SPEC_CATEGORY = """CASE WHEN f.check_id LIKE 'sae\\_%%' OR f.check_id = 'chk_22' THEN 'sae_recon'
                        WHEN f.check_id IN ('chk_24','chk_25','chk_26') THEN 'lab_recon' ELSE s.ctq_category END"""


@dataclass
class Hypothetical:
    """A what-if (milestone 15): faster answers at some sites, or a whole class of work already done."""
    site_response_days: dict[str, float] = field(default_factory=dict)
    close_categories: list[str] = field(default_factory=list)
    description: str = ""


def to_date(today: date, days: float) -> date:
    return today + timedelta(days=int(round(days)))


class ForecastService:
    def __init__(self, conn: Connection, n_sims: int = 2000):
        self.conn, self.n_sims = conn, n_sims

    def _samplers(self, today: date) -> tuple[dict[str, MixtureSampler], MixtureSampler]:
        rows = self.conn.execute("SELECT site_id, opened_on, closed_on, state FROM ops.queries WHERE opened_on IS NOT NULL").fetchall()
        by_site: dict[str, tuple[list, list]] = {}
        all_d, all_e = [], []
        for site, opened, closed, state in rows:
            done = state in ("Closed", "ClosedWithExplanation") and closed is not None
            d = max(0.5, float(((closed if done else today) - opened).days))
            by_site.setdefault(site, ([], []))[0].append(d)
            by_site[site][1].append(done)
            all_d.append(d)
            all_e.append(done)
        pooled_km = KmSampler(all_d, all_e) if any(all_e) else KmSampler([5.0, 8.0, 10.0, 14.0], [True] * 4)       # weak prior before any query has closed
        pooled = MixtureSampler(pooled_km, pooled_km)
        return {s: MixtureSampler(KmSampler(d, e) if any(e) else None, pooled_km) for s, (d, e) in by_site.items()}, pooled

    def build(self, today: date, hyp: Hypothetical | None = None) -> tuple[Items, dict]:
        c = self.conn
        items = Items()
        lag = {s: float(v) for s, v in c.execute(
            "SELECT site_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY lag) FROM (SELECT site_id, entered_at - actual_date AS lag FROM edc.visits "
            "UNION ALL SELECT site_id, entered_at - measured_at::date FROM edc.vitals) x GROUP BY 1")}
        pooled_lag = median(lag.values()) if lag else 3.0
        close = set(hyp.close_categories) if hyp else set()

        for site, opened, cat in c.execute(
                f"SELECT q.site_id, q.opened_on, {SPEC_CATEGORY} FROM ops.queries q JOIN ops.check_failures f ON f.id = q.failure_id "
                f"JOIN ops.check_specs s ON s.id = f.check_id WHERE q.state IN ('Draft','Approved','Sent','Answered','Reopened')"):
            items.add("open_query", site, cat, age=float((today - opened).days))

        opened_by_site = dict(c.execute("SELECT site_id, count(*) FROM ops.queries GROUP BY 1").fetchall())
        visits_by_site = dict(c.execute("SELECT site_id, count(*) FROM edc.visits GROUP BY 1").fetchall())
        schedule = dict(SCHEDULE)
        last_planned = {u: p for u, p in c.execute("SELECT usubjid, max(planned_day) FROM edc.visits WHERE visit = ANY(%s) GROUP BY 1", ([v for v, _ in SCHEDULE],))}
        ongoing = c.execute("SELECT s.usubjid, s.site_id, COALESCE((SELECT min(actual_date) FROM edc.visits v WHERE v.usubjid = s.usubjid AND v.visit = 'BASELINE'), s.consent_at + 14) "
                            "FROM edc.subjects s WHERE s.status = 'enrolled'").fetchall()
        n_visits_left = 0
        last_visit_day = today
        for u, site, base in ongoing:
            l = lag.get(site, pooled_lag)
            lam = min(0.8, max(0.02, opened_by_site.get(site, 0) / max(1, visits_by_site.get(site, 0))))
            remaining = [(v, p) for v, p in schedule.items() if p > (last_planned.get(u) or 0)]
            end = base + timedelta(days=181)
            last_visit_day = max(last_visit_day, end)
            items.add("last_visit", site, "visits", offset=max(0.0, (end - today).days) + l, resolves=False)
            n_visits_left += len(remaining)
            for _v, p in sorted(remaining, key=lambda x: x[1])[-2:]:                      # the latest visits dominate the finish line
                items.add("expected_query", site, "expected", offset=max(0.0, (base + timedelta(days=p - 1) - today).days) + l, prob=lam)

        enrolled = c.execute("SELECT count(*) FROM edc.subjects").fetchone()[0]
        recent = c.execute("SELECT count(*) FROM edc.subjects WHERE consent_at > %s", (today - timedelta(days=56),)).fetchone()[0]
        start = c.execute("SELECT study_start FROM ops.sim_clock").fetchone()[0]
        rate = max(recent / 56, enrolled / max(1, (today - start).days) * 0.5, 0.05)
        remaining_to_enrol = max(0, PLANNED_ENROLLMENT - enrolled)
        enrollment = {"enrolled": enrolled, "planned": PLANNED_ENROLLMENT, "remaining": remaining_to_enrol, "rate_per_day": rate,
                      "followup_days": FOLLOWUP_DAYS, "entry_lag": pooled_lag}
        if remaining_to_enrol > 0:
            items.add("enrollment", None, "enrollment", resolves=False)
        lplv = max(last_visit_day, today + timedelta(days=int(remaining_to_enrol / rate + FOLLOWUP_DAYS))) if remaining_to_enrol else last_visit_day
        return items, {"enrollment": enrollment if remaining_to_enrol > 0 else None, "lplv": lplv, "visits_left": n_visits_left, "ongoing": len(ongoing),
                       "enrolled": enrolled, "enrollment_info": enrollment}

    def run(self, today: date, hyp: Hypothetical | None = None) -> dict:
        seed = self.conn.execute("SELECT value FROM ops.sim_state WHERE key = 'sim_seed'").fetchone()
        rng = np.random.default_rng([int(seed[0]) if seed else 42, today.toordinal(), 9])
        items, ctx = self.build(today, hyp)
        samplers, pooled = self._samplers(today)
        mask = np.array([c in set(hyp.close_categories) for c in items.category], dtype=bool) if hyp and hyp.close_categories and len(items) else None
        sim = simulate(items, samplers, pooled, rng, self.n_sims, enrollment=ctx["enrollment"],
                       response_override=(hyp.site_response_days if hyp else None), ignore_mask=mask, override_seed=today.toordinal())
        p10, p50, p90 = percentiles(sim)
        crit = readiness.criteria(self.conn, today)
        kinds = {k: items.kind.count(k) for k in set(items.kind)}
        p50_date = to_date(today, p50)
        return {"sim_date": today, "p10": to_date(today, p10), "p50": p50_date, "p90": to_date(today, p90), "n_sims": self.n_sims,
                "readiness": {"criteria": crit, "met": sum(c["met"] for c in crit), "total": len(crit)},
                "blockers": blockers(sim, items),
                "benchmark": {"lplv": str(ctx["lplv"]), "days_lplv_to_p50": (p50_date - ctx["lplv"]).days, "tufts_days": TUFTS_DAYS},
                "enrollment": ctx["enrollment_info"], "items": kinds, "ongoing_subjects": ctx["ongoing"]}

    def store(self, res: dict) -> None:
        payload = {"criteria": res["readiness"]["criteria"], "met": res["readiness"]["met"], "total": res["readiness"]["total"],
                   "benchmark": res["benchmark"], "enrollment": res["enrollment"], "items": res["items"]}
        self.conn.execute("INSERT INTO ops.lock_forecasts (sim_date, p10, p50, p90, readiness, blockers, n_sims) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                          "ON CONFLICT (sim_date) DO UPDATE SET p10 = EXCLUDED.p10, p50 = EXCLUDED.p50, p90 = EXCLUDED.p90, readiness = EXCLUDED.readiness, "
                          "blockers = EXCLUDED.blockers, n_sims = EXCLUDED.n_sims",
                          (res["sim_date"], res["p10"], res["p50"], res["p90"], json.dumps(payload, default=str), json.dumps(res["blockers"]), res["n_sims"]))

    def run_and_store(self, today: date) -> dict:
        res = self.run(today)
        self.store(res)
        return res
