-- Milestone 11: hub views over the external feeds (no treatment arm anywhere). Views run with the owner's rights, so a role can read a
-- feed through its view without access to the raw table; aggregate views are what the study lead may see.
CREATE VIEW hub.v_lab_vendor AS
SELECT t.id, t.file_date, t.released, t.patient_ref, x.canonical_subject AS usubjid, t.test_name, m.test_code,
       CASE WHEN t.result ~ '^-?[0-9]+(\.[0-9]+)?$' THEN t.result::double precision END AS result, t.unit,
       CASE WHEN t.collected ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN to_date(t.collected, 'DD/MM/YYYY') END AS collected
FROM lab_vendor.transfer t
LEFT JOIN hub.subject_xwalk x ON x.system = 'lab_vendor' AND x.source_id = t.patient_ref AND x.status <> 'rejected'
LEFT JOIN hub.lab_test_map m ON lower(m.test_name) = lower(t.test_name);

CREATE VIEW hub.v_safety_cases AS
SELECT c.*, x.canonical_subject AS usubjid
FROM safety.v_cases c
LEFT JOIN hub.subject_xwalk x ON x.system = 'safety' AND x.source_id = c.subject_ref AND x.status <> 'rejected';

CREATE VIEW hub.v_irt_kits AS
SELECT k.kit_no, k.patient_ref, k.dispensed, x.canonical_subject AS usubjid
FROM irt.kits k
LEFT JOIN hub.subject_xwalk x ON x.system = 'irt' AND x.source_id = k.patient_ref AND x.status <> 'rejected';

CREATE VIEW hub.v_ctms_sites AS
SELECT c.site_code, c.site_name, c.city, c.activated, x.canonical_site AS site_id, x.method, x.confidence, x.status
FROM ctms.sites c
LEFT JOIN hub.site_xwalk x ON x.system = 'ctms' AND x.source_id = c.site_code;

CREATE VIEW hub.v_site_monitoring AS
SELECT x.canonical_site AS site_id, max(m.visit_date) FILTER (WHERE m.visit_date <= (SELECT today FROM ops.sim_clock) AND m.visit_date > DATE '2000-01-01') AS last_monitoring_visit
FROM hub.site_xwalk x
LEFT JOIN ctms.monitoring_visits m ON m.site_code = x.source_id
WHERE x.system = 'ctms' AND x.canonical_site IS NOT NULL AND x.status <> 'rejected'
GROUP BY 1;

CREATE VIEW hub.v_open_items AS
SELECT s.site_id,
  (SELECT count(*) FROM ops.queries q WHERE q.site_id = s.site_id AND q.state IN ('Draft','Approved','Sent','Answered','Reopened')) AS open_queries,
  (SELECT count(*) FROM ops.queries q JOIN ops.check_failures f ON f.id = q.failure_id JOIN ops.check_specs sp ON sp.id = f.check_id
    WHERE q.site_id = s.site_id AND sp.severity = 'critical' AND q.state IN ('Draft','Approved','Sent','Answered','Reopened')) AS open_critical_queries,
  (SELECT count(*) FROM ops.check_failures f WHERE f.site_id = s.site_id AND f.resolved_on IS NULL AND (f.check_id LIKE 'sae\_%' OR f.check_id = 'chk_22')) AS open_sae_discrepancies,
  (SELECT count(*) FROM ops.check_failures f WHERE f.site_id = s.site_id AND f.resolved_on IS NULL AND f.check_id IN ('chk_24','chk_25','chk_26')) AS open_lab_differences
FROM edc.sites s;

CREATE VIEW hub.v_site_counts AS
SELECT s.site_id,
  (SELECT count(*) FROM edc.exposure e JOIN edc.subjects u USING (usubjid) WHERE u.site_id = s.site_id AND e.start_at > COALESCE(u.discontinued_at, u.death_at)) AS dosing_after_discontinuation,
  (SELECT count(*) FROM hub.v_irt_kits k JOIN edc.subjects u USING (usubjid) WHERE u.site_id = s.site_id AND k.dispensed > u.discontinued_at) AS kits_after_discontinuation,
  (SELECT count(DISTINCT a.usubjid) FROM edc.lab a JOIN edc.lab b ON b.usubjid = a.usubjid AND b.test_code = 'BILI' AND b.x_uln >= 2
        AND abs(b.collected_at::date - a.collected_at::date) <= 30
    WHERE a.site_id = s.site_id AND a.test_code IN ('ALT','AST') AND a.x_uln >= 3
      AND EXISTS (SELECT 1 FROM ops.check_failures f WHERE f.usubjid = a.usubjid AND f.resolved_on IS NULL AND (f.check_id LIKE 'sae\_%' OR f.check_id = 'chk_22'))) AS hys_with_open_sae
FROM edc.sites s;

GRANT SELECT ON hub.v_lab_vendor, hub.v_safety_cases, hub.v_irt_kits, hub.v_ctms_sites, hub.v_site_monitoring TO data_manager, medical_monitor, central_monitor, eval_admin;
GRANT SELECT ON hub.v_open_items, hub.v_site_counts TO data_manager, medical_monitor, central_monitor, study_lead, eval_admin;
GRANT SELECT ON hub.v_site_monitoring TO study_lead;
GRANT SELECT, INSERT, UPDATE ON hub.catalog, hub.dq_results TO data_manager, medical_monitor, central_monitor;
GRANT SELECT ON hub.catalog, hub.dq_results, hub.site_xwalk, hub.subject_xwalk TO study_lead, eval_admin;
