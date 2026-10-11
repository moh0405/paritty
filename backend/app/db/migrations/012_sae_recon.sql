-- Additive to spec §8: flattened safety cases (citable by claims, comparable by the matcher) and recon history.
CREATE VIEW safety.v_cases AS
SELECT id, safetyreportid, version, subject_ref, to_date(receivedate, 'YYYYMMDD') AS received, causality, narrative, available_on,
       payload->>'serious' AS serious,
       payload->'patient'->'reaction'->0->>'reactionmeddrapt' AS reaction_term,
       to_date(payload->'patient'->'reaction'->0->>'reactionstartdate', 'YYYYMMDD') AS onset,
       payload->'patient'->'reaction'->0->>'reactionoutcome' AS outcome,
       payload->>'seriousnessdeath' AS death
FROM safety.case_versions;
CREATE TABLE ops.sae_recon_history (sim_date date PRIMARY KEY, counts jsonb NOT NULL);
GRANT SELECT ON safety.v_cases TO data_manager, medical_monitor, central_monitor, eval_admin;
GRANT SELECT, INSERT, UPDATE ON ops.sae_recon_history TO data_manager, medical_monitor, central_monitor;
GRANT SELECT ON ops.sae_recon_history TO study_lead, eval_admin;
GRANT INSERT, UPDATE, DELETE ON safety.case_versions TO data_manager;   -- the simulated safety desk issues follow-up versions
GRANT USAGE ON SEQUENCE safety.case_versions_id_seq TO data_manager;
