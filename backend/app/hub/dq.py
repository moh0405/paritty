"""Data-quality rules across the hub (spec §9.9): completeness, validity, consistency, timeliness -> hub.dq_results."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from psycopg import Connection

from app.audit.logger import sim_ts


@dataclass(frozen=True)
class Rule:
    id: str
    table: str
    dimension: str
    description: str
    pk_sql: str          # SELECT of the primary-key text of each failing row; %(t)s is the simulated today


RULES: list[Rule] = [
    Rule("subjects_missing_consent", "edc.subjects", "completeness", "Subjects with no consent date", "SELECT usubjid FROM edc.subjects WHERE consent_at IS NULL"),
    Rule("serious_ae_missing_outcome", "edc.ae", "completeness", "Serious adverse events with no outcome", "SELECT id::text FROM edc.ae WHERE serious AND outcome IS NULL"),
    Rule("core_lab_missing_unit", "edc.lab", "completeness", "Core safety lab results with no unit",
         "SELECT id::text FROM edc.lab WHERE unit IS NULL AND test_code IN ('ALT','AST','ALP','BILI','CREAT','HGB','PLAT')"),
    Rule("baseline_without_kit", "irt.kits", "completeness", "Subjects past baseline with no study kit recorded",
         "SELECT v.usubjid FROM edc.visits v WHERE v.visit = 'BASELINE' AND v.actual_date < %(t)s - 14 AND NOT EXISTS (SELECT 1 FROM hub.v_irt_kits k WHERE k.usubjid = v.usubjid)"),
    Rule("ctms_impossible_dates", "ctms.monitoring_visits", "validity", "Monitoring visits or deviations with an impossible date",
         "SELECT 'visit ' || id FROM ctms.monitoring_visits WHERE visit_date < DATE '2000-01-01' OR visit_date > DATE '2100-01-01' "
         "UNION ALL SELECT 'deviation ' || id FROM ctms.deviations WHERE occurred < DATE '2000-01-01' OR occurred > DATE '2100-01-01'"),
    Rule("vendor_result_not_numeric", "lab_vendor.transfer", "validity", "Central-lab results that are not numeric",
         "SELECT id::text FROM hub.v_lab_vendor WHERE released AND file_date <= %(t)s AND result IS NULL"),
    Rule("duplicate_deviations", "ctms.deviations", "consistency", "Duplicate protocol deviation records",
         "SELECT min(id)::text FROM ctms.deviations GROUP BY site_code, patient_ref, category, occurred HAVING count(*) > 1"),
    Rule("orphan_kits", "irt.kits", "consistency", "Kits dispensed to a patient reference that matches no subject",
         "SELECT kit_no FROM hub.v_irt_kits WHERE usubjid IS NULL AND dispensed <= %(t)s"),
    Rule("kit_after_discontinuation", "irt.kits", "consistency", "Kits dispensed after the subject discontinued",
         "SELECT k.kit_no FROM hub.v_irt_kits k JOIN edc.subjects s USING (usubjid) WHERE k.dispensed > s.discontinued_at AND k.dispensed <= %(t)s"),
    Rule("dosing_after_discontinuation", "edc.exposure", "consistency", "Dosing recorded after discontinuation or death",
         "SELECT e.id::text FROM edc.exposure e JOIN edc.subjects s USING (usubjid) WHERE e.start_at > COALESCE(s.discontinued_at, s.death_at)"),
    Rule("unmapped_lab_patients", "lab_vendor.transfer", "consistency", "Central-lab patient references not matched to a subject",
         "SELECT DISTINCT patient_ref FROM hub.v_lab_vendor WHERE released AND file_date <= %(t)s AND usubjid IS NULL"),
    Rule("duplicate_site_records", "ctms.sites", "consistency", "CTMS site records that duplicate another record",
         "SELECT site_code FROM hub.v_ctms_sites WHERE method = 'duplicate_record'"),
    Rule("unmatched_site_records", "ctms.sites", "consistency", "CTMS site records with no matching EDC site",
         "SELECT site_code FROM hub.v_ctms_sites WHERE site_id IS NULL"),
    Rule("lab_feed_stale", "lab_vendor.transfer", "timeliness", "Central-lab feed has not delivered a file for more than 3 days",
         "SELECT 'central lab' WHERE (SELECT max(file_date) FROM lab_vendor.transfer WHERE released AND file_date <= %(t)s) < %(t)s - 3"),
    Rule("late_visit_entry", "edc.visits", "timeliness", "Visits entered more than 14 days after the visit",
         "SELECT id::text FROM edc.visits WHERE entered_at - actual_date > 14"),
    Rule("stale_queries", "ops.queries", "timeliness", "Queries waiting for a site answer for more than 14 days",
         "SELECT id::text FROM ops.queries WHERE state = 'Sent' AND sent_on < %(t)s - 14"),
]
DIMENSIONS = ["completeness", "validity", "consistency", "timeliness"]


def run(conn: Connection, day: date) -> list[dict]:
    out = []
    for r in RULES:
        n, sample = conn.execute(f"SELECT count(*), (array_agg(pk ORDER BY pk))[1:5] FROM ({r.pk_sql}) x(pk)", {"t": day}).fetchone()
        conn.execute("INSERT INTO hub.dq_results (ts, sim_date, rule, table_name, dimension, failed_rows, sample_pks) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                     (sim_ts(day), day, r.id, r.table, r.dimension, n, sample or []))
        out.append({"rule": r.id, "failed_rows": n})
    return out


def latest(conn: Connection) -> list[dict]:
    desc = {r.id: r.description for r in RULES}
    cur = conn.execute("SELECT DISTINCT ON (rule) rule, table_name, dimension, failed_rows, sample_pks, sim_date FROM hub.dq_results ORDER BY rule, ts DESC")
    rows = [{"rule": a, "table": b, "dimension": c, "failed_rows": d, "sample_pks": e, "sim_date": str(f), "description": desc.get(a, a)} for a, b, c, d, e, f in cur.fetchall()]
    return sorted(rows, key=lambda x: (DIMENSIONS.index(x["dimension"]), -x["failed_rows"]))
