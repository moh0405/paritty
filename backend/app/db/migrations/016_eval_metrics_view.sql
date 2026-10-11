-- Milestone 16: eval metrics become citable (a summary sentence cites the metric row it reports). Aggregate numbers only, no patient data.
CREATE VIEW eval.v_metrics AS
SELECT scenario_run_id || '|' || module || '|' || metric AS ref, scenario_run_id, module, metric, value, detail
FROM eval.metrics;
GRANT USAGE ON SCHEMA eval TO data_manager, medical_monitor, central_monitor, study_lead;
GRANT SELECT ON eval.v_metrics TO data_manager, medical_monitor, central_monitor, study_lead, eval_admin;
GRANT SELECT ON eval.scenario_runs TO data_manager, medical_monitor, central_monitor, study_lead;
