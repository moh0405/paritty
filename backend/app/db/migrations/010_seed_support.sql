-- Additive to spec §8: scheduled subject-level updates (disposition/death must not leak before they happen)
-- and a lab test-name map used by the vendor feed and recon.
CREATE TABLE edc_pending.subject_updates (id bigserial PRIMARY KEY, usubjid text NOT NULL, apply_on date NOT NULL,
  status text, discontinued_at date, death_at date, applied bool DEFAULT false);
CREATE TABLE hub.lab_test_map (test_code text PRIMARY KEY, test_name text NOT NULL);
GRANT SELECT ON hub.lab_test_map TO data_manager, medical_monitor, central_monitor, eval_admin;
GRANT SELECT, UPDATE ON edc_pending.subject_updates TO data_manager, medical_monitor, central_monitor;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA edc_pending TO data_manager, medical_monitor, central_monitor;
