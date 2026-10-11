"""Key risk indicators per site with red/amber/green status (spec §9.7)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Callable

from psycopg import Connection

from app.sim.constants import VISIT_WINDOW_DAYS
from app.sim.schedule import SCHEDULE

SITE_FROM_CODE = "substring(site_code from 'SITE-0*([0-9]+)')"
MIN_PATIENT_MONTHS = 3.0


# ---- RAG rules (pure) ---------------------------------------------------------------------------------
def rag_ratio_both(v: float, med: float) -> str:
    """Two-sided: red outside 0.5x-2x of the median, amber outside 0.67x-1.5x."""
    if med <= 0:
        return "na"
    r = v / med
    return "red" if (r < 0.5 or r > 2.0) else "amber" if (r < 0.67 or r > 1.5) else "green"


def rag_ratio_high(v: float, med: float) -> str:
    """High is bad: red above 2x the median, amber above 1.5x."""
    if med <= 0:
        return "green" if v <= 0 else "na"
    r = v / med
    return "red" if r > 2.0 else "amber" if r > 1.5 else "green"


def rag_abs_high(red: float, amber: float) -> Callable[[float, float], str]:
    return lambda v, _med: "red" if v > red else "amber" if v > amber else "green"


def rag_z(values: dict[str, float], site: str) -> str:
    from app.medical.signals import robust_z
    z = robust_z(values).get(site, 0.0)
    return "red" if z > 3 else "amber" if z > 2 else "green"


@dataclass
class KriValue:
    site_id: str
    kri: str
    value: float | None
    comparator: float | None
    rag: str


# ---- raw measurements ----------------------------------------------------------------------------------
def _by_site(conn: Connection, sql: str, params: dict) -> dict[str, float]:
    return {s: float(v) for s, v in conn.execute(sql, params).fetchall() if v is not None}


def patient_months(conn: Connection, today: date) -> dict[str, float]:
    return _by_site(conn, "SELECT site_id, sum(GREATEST(0, COALESCE(discontinued_at, death_at, %(t)s)::date - consent_at)) / 30.4375 "
                          "FROM edc.subjects GROUP BY 1", {"t": today})


def measure(conn: Connection, today: date) -> dict[str, dict[str, float]]:
    pm = patient_months(conn, today)
    P = {"t": today, "w": VISIT_WINDOW_DAYS}
    ae = _by_site(conn, "SELECT site_id, count(*) FROM edc.ae GROUP BY 1", P)
    sae = _by_site(conn, "SELECT site_id, count(*) FROM edc.ae WHERE serious GROUP BY 1", P)
    points = _by_site(conn, "SELECT site_id, count(*) FROM (SELECT site_id FROM edc.lab UNION ALL SELECT site_id FROM edc.vitals UNION ALL SELECT site_id FROM edc.ae) x GROUP BY 1", P)
    queries = _by_site(conn, "SELECT site_id, count(*) FROM ops.queries GROUP BY 1", P)
    resolution = _by_site(conn, "SELECT site_id, CASE WHEN count(*) >= 3 THEN percentile_cont(0.5) WITHIN GROUP (ORDER BY closed_on - opened_on) END "
                                "FROM ops.queries WHERE state IN ('Closed','ClosedWithExplanation') AND closed_on IS NOT NULL GROUP BY 1", P)
    lag = _by_site(conn, "SELECT site_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY lag) FROM (SELECT site_id, entered_at - measured_at::date AS lag FROM edc.vitals "
                         "UNION ALL SELECT site_id, entered_at - actual_date FROM edc.visits UNION ALL SELECT site_id, entered_at - onset_at FROM edc.ae WHERE onset_at IS NOT NULL) x GROUP BY 1", P)
    subjects = _by_site(conn, "SELECT site_id, count(*) FROM edc.subjects GROUP BY 1", P)
    dev = _by_site(conn, f"SELECT {SITE_FROM_CODE}, count(*) FROM ctms.deviations WHERE occurred <= %(t)s GROUP BY 1", P)
    window = _by_site(conn, "SELECT t.site_id, avg((abs(t.actual_date - (b.actual_date + t.planned_day - 1)) > %(w)s)::int) FROM edc.visits t "
                            "JOIN edc.visits b ON b.usubjid = t.usubjid AND b.visit = 'BASELINE' WHERE t.visit = ANY(%(v)s) GROUP BY 1",
                      {**P, "v": [v for v, _ in SCHEDULE]})
    scr = {s: (f, n) for s, f, n in conn.execute(f"SELECT {SITE_FROM_CODE}, count(*) FILTER (WHERE outcome = 'Failed'), count(*) FROM ctms.screening "
                                                 f"WHERE screened <= %(t)s GROUP BY 1", P).fetchall()}
    out: dict[str, dict[str, float]] = {"ae_rate": {}, "sae_rate": {}, "query_rate": {}, "query_resolution_days": {}, "entry_lag_days": {},
                                        "deviations_per_patient": {}, "visit_window_violations": {}, "screen_failure_rate": {}}
    for s, m in pm.items():
        if m >= MIN_PATIENT_MONTHS:
            out["ae_rate"][s] = ae.get(s, 0) / m
            out["sae_rate"][s] = sae.get(s, 0) / m * 100
        if points.get(s):
            out["query_rate"][s] = queries.get(s, 0) / points[s] * 100
        if subjects.get(s):
            out["deviations_per_patient"][s] = dev.get(s, 0) / subjects[s]
    out["query_resolution_days"], out["entry_lag_days"], out["visit_window_violations"] = resolution, lag, window
    out["screen_failure_rate"] = {s: f / n for s, (f, n) in scr.items() if n >= 5}
    return out


# ---- KRI definitions (Strategy: one entry per indicator) -------------------------------------------------------
KRI_DEFS: dict[str, dict] = {
    "ae_rate": {"label": "Adverse events per patient-month", "rag": rag_ratio_both, "unit": "per patient-month", "rule": "red outside 0.5x-2x of the median site, amber outside 0.67x-1.5x"},
    "sae_rate": {"label": "Serious adverse events per 100 patient-months", "rag": rag_ratio_both, "unit": "per 100 patient-months", "rule": "red outside 0.5x-2x of the median site, amber outside 0.67x-1.5x"},
    "query_rate": {"label": "Queries per 100 data points", "rag": rag_ratio_high, "unit": "per 100 data points", "rule": "red above 2x the median site, amber above 1.5x"},
    "query_resolution_days": {"label": "Median query resolution (days)", "rag": rag_abs_high(21, 14), "unit": "days", "rule": "red above 21 days, amber above 14"},
    "entry_lag_days": {"label": "Median data entry lag (days)", "rag": rag_abs_high(14, 7), "unit": "days", "rule": "red above 14 days, amber above 7"},
    "deviations_per_patient": {"label": "Protocol deviations per patient", "rag": rag_ratio_high, "unit": "per patient", "rule": "red above 2x the median site, amber above 1.5x"},
    "visit_window_violations": {"label": "Visits outside the protocol window", "rag": rag_abs_high(0.20, 0.10), "unit": "share of visits", "rule": "red above 20%, amber above 10%"},
    "screen_failure_rate": {"label": "Screen-failure rate", "rag": None, "unit": "share of screened", "rule": "red above 3, amber above 2 robust z-scores vs other sites"},
}


def compute_kris(conn: Connection, today: date) -> list[KriValue]:
    data = measure(conn, today)
    out: list[KriValue] = []
    for name, d in KRI_DEFS.items():
        vals = data[name]
        med = median(vals.values()) if vals else None
        for site, v in vals.items():
            rag = rag_z(vals, site) if name == "screen_failure_rate" else d["rag"](v, med if med is not None else 0.0)
            out.append(KriValue(site, name, v, med, rag))
    return out


def store_kris(conn: Connection, day: date, kris: list[KriValue]) -> None:
    for k in kris:
        conn.execute("INSERT INTO ops.kri_values (sim_date, site_id, kri, value, comparator, rag) VALUES (%s,%s,%s,%s,%s,%s) "
                     "ON CONFLICT (sim_date, site_id, kri) DO UPDATE SET value = EXCLUDED.value, comparator = EXCLUDED.comparator, rag = EXCLUDED.rag",
                     (day, k.site_id, k.kri, k.value, k.comparator, k.rag))
