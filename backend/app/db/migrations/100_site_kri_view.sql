-- Milestone 13: one KRI value as a citable row, so agenda and letter claims can cite it (ref = '<sim_date>:<site>:<kri>').
CREATE VIEW ops.v_kri AS
SELECT sim_date::text || ':' || site_id || ':' || kri AS ref, sim_date, site_id, kri, value, comparator, rag FROM ops.kri_values;
GRANT SELECT ON ops.v_kri TO data_manager, medical_monitor, central_monitor, study_lead, eval_admin;
