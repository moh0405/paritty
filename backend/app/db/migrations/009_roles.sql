DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['data_manager','medical_monitor','central_monitor','study_lead','unblinded_statistician'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN EXECUTE format('CREATE ROLE %I NOLOGIN', r); END IF;
    EXECUTE format('GRANT %I TO CURRENT_USER', r);   -- lets the app connection SET ROLE
  END LOOP;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eval_admin') THEN
    CREATE ROLE eval_admin LOGIN PASSWORD 'lockstep';  -- local dev password; override on Tiger
  END IF;
END $$;

REVOKE ALL ON SCHEMA unblinded, answer_key FROM PUBLIC;
GRANT USAGE ON SCHEMA unblinded TO unblinded_statistician;
GRANT SELECT ON ALL TABLES IN SCHEMA unblinded TO unblinded_statistician;
GRANT USAGE ON SCHEMA answer_key, eval, edc, ops, ai, hub, safety, ctms, irt, lab_vendor TO eval_admin;
GRANT SELECT ON ALL TABLES IN SCHEMA answer_key, eval, edc, ops, ai, hub, safety, ctms, irt, lab_vendor TO eval_admin;
GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA answer_key, eval TO eval_admin;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA answer_key, eval TO eval_admin;

-- Patient-level roles: everything except unblinded/answer_key/audit writes.
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['data_manager','medical_monitor','central_monitor'] LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA edc, edc_pending, ops, ai, hub, safety, mock_safety, ctms, irt, lab_vendor, audit TO %I', r);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA edc, edc_pending, ops, ai, hub, mock_safety, audit TO %I', r);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA safety, ctms, irt, lab_vendor TO %I', r);
    EXECUTE format('GRANT USAGE ON ALL SEQUENCES IN SCHEMA edc, edc_pending, ops, ai, hub, mock_safety, audit TO %I', r);
  END LOOP;
END $$;

-- study_lead: aggregates only (no patient-level tables).
GRANT USAGE ON SCHEMA hub, ops TO study_lead;
GRANT SELECT ON hub.v_site_summary TO study_lead;
GRANT SELECT ON ops.lock_forecasts, ops.kri_values, ops.site_risk TO study_lead;

-- unblinded_statistician also needs the blinded views to join against.
GRANT USAGE ON SCHEMA hub TO unblinded_statistician;
GRANT SELECT ON hub.v_subjects, hub.v_site_summary TO unblinded_statistician;

-- Row-level security on patient-level EDC tables (site scope).
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['ae','lab','vitals','subjects'] LOOP
    EXECUTE format('ALTER TABLE edc.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY site_scope ON edc.%I USING (
      current_setting('app.site_scope', true) IS NULL OR current_setting('app.site_scope', true) = ''
      OR site_id = ANY(string_to_array(current_setting('app.site_scope', true), ',')))$p$, t);
  END LOOP;
END $$;
