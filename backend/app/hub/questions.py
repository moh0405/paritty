"""The five fixed cross-system questions (spec §9.9). Each has a patient-level form and, where a role cannot read patient rows,
an aggregate form over site-level views - so the same question returns different results per role."""
from __future__ import annotations

import psycopg
from psycopg import Connection

TODAY = "(SELECT today FROM ops.sim_clock)"

QUESTIONS: list[dict] = [
    {"id": 1, "title": "Sites with open critical queries AND unreconciled serious adverse events",
     "tables": ["ops.queries", "ops.check_failures", "ops.check_specs"],
     "patient_sql": "SELECT site_id, open_critical_queries, open_sae_discrepancies FROM hub.v_open_items WHERE open_critical_queries > 0 AND open_sae_discrepancies > 0 ORDER BY open_critical_queries DESC",
     "aggregate_sql": None},
    {"id": 2, "title": "Subjects dosed after discontinuation",
     "tables": ["edc.exposure", "edc.subjects"],
     "patient_sql": "SELECT s.usubjid, s.site_id, e.start_at AS dosed_on, COALESCE(s.discontinued_at, s.death_at) AS stopped_on FROM edc.exposure e JOIN edc.subjects s USING (usubjid) "
                    "WHERE e.start_at > COALESCE(s.discontinued_at, s.death_at) ORDER BY s.site_id, s.usubjid",
     "aggregate_sql": "SELECT site_id, dosing_after_discontinuation AS subjects FROM hub.v_site_counts WHERE dosing_after_discontinuation > 0 ORDER BY site_id"},
    {"id": 3, "title": "Kits dispensed to discontinued subjects",
     "tables": ["irt.kits", "hub.subject_xwalk", "edc.subjects"],
     "patient_sql": "SELECT k.kit_no, k.usubjid, s.site_id, k.dispensed, s.discontinued_at FROM hub.v_irt_kits k JOIN edc.subjects s USING (usubjid) WHERE k.dispensed > s.discontinued_at ORDER BY k.dispensed",
     "aggregate_sql": "SELECT site_id, kits_after_discontinuation AS kits FROM hub.v_site_counts WHERE kits_after_discontinuation > 0 ORDER BY site_id"},
    {"id": 4, "title": "Sites with red risk indicators and no monitoring visit in 60 days",
     "tables": ["ops.kri_values", "ctms.monitoring_visits", "hub.site_xwalk"],
     "patient_sql": "WITH red AS (SELECT site_id, count(*) AS red_indicators FROM ops.kri_values WHERE sim_date = (SELECT max(sim_date) FROM ops.kri_values) AND rag = 'red' GROUP BY 1) "
                    f"SELECT r.site_id, r.red_indicators, m.last_monitoring_visit FROM red r LEFT JOIN hub.v_site_monitoring m USING (site_id) "
                    f"WHERE m.last_monitoring_visit IS NULL OR m.last_monitoring_visit < {TODAY} - 60 ORDER BY r.red_indicators DESC",
     "aggregate_sql": None},
    {"id": 5, "title": "Subjects with a potential Hy's Law pattern AND open safety-case discrepancies",
     "tables": ["edc.lab", "ops.check_failures", "safety.case_versions"],
     "patient_sql": "SELECT DISTINCT a.usubjid, a.site_id FROM edc.lab a JOIN edc.lab b ON b.usubjid = a.usubjid AND b.test_code = 'BILI' AND b.x_uln >= 2 "
                    "AND abs(b.collected_at::date - a.collected_at::date) <= 30 WHERE a.test_code IN ('ALT','AST') AND a.x_uln >= 3 AND EXISTS (SELECT 1 FROM ops.check_failures f "
                    "WHERE f.usubjid = a.usubjid AND f.resolved_on IS NULL AND (f.check_id LIKE 'sae\\_%%' OR f.check_id = 'chk_22')) ORDER BY a.site_id, a.usubjid",
     "aggregate_sql": "SELECT site_id, hys_with_open_sae AS subjects FROM hub.v_site_counts WHERE hys_with_open_sae > 0 ORDER BY site_id"},
]


def catalog() -> list[dict]:
    return [{"id": q["id"], "title": q["title"], "tables": q["tables"]} for q in QUESTIONS]


def run(conn: Connection, n: int) -> dict:
    """Run on a connection that is already acting as the caller's role. Falls back to the aggregate form when patient rows are not readable."""
    q = next((x for x in QUESTIONS if x["id"] == n), None)
    if q is None:
        raise KeyError(n)
    attempts = [("patient-level", q["patient_sql"])] + ([("site-level", q["aggregate_sql"])] if q["aggregate_sql"] else [])
    note = ""
    for level, sql in attempts:
        try:
            with conn.transaction():
                cur = conn.execute(sql)
                cols = [d.name for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            if level == "site-level" and note == "":
                note = "Your role can't see patient-level rows, so this shows counts by site."
            return {"id": n, "title": q["title"], "level": level, "columns": cols, "rows": rows, "note": note,
                    "lineage": {"sql": sql, "tables": q["tables"], "row_refs": _refs(rows, q["tables"])}}
        except psycopg.errors.InsufficientPrivilege:
            note = "Your role can't see patient-level rows, so this shows counts by site."
    raise PermissionError("Your role can't see the data behind this question.")


def _refs(rows: list[dict], tables: list[str]) -> list[dict]:
    key = next((k for k in ("usubjid", "kit_no", "site_id") if rows and k in rows[0]), None)
    return [{"table": tables[0], "pk": str(r[key])} for r in rows[:20]] if key else []
