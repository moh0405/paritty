CREATE TABLE lab_vendor.transfer (id bigserial PRIMARY KEY, file_date date NOT NULL, accession_no text,
  patient_ref text, test_name text, result text, unit text, collected text, released bool DEFAULT false);
CREATE TABLE safety.case_versions (id bigserial PRIMARY KEY, safetyreportid text NOT NULL, version int NOT NULL,
  receivedate text, subject_ref text, payload jsonb NOT NULL, causality text, narrative text,
  available_on date NOT NULL, UNIQUE (safetyreportid, version));
CREATE TABLE mock_safety.inbox (id bigserial PRIMARY KEY, received_at timestamptz DEFAULT now(),
  message jsonb, source_ae_id bigint, status text);
CREATE TABLE ctms.sites (site_code text PRIMARY KEY, site_name text, city text, activated date);
CREATE TABLE ctms.deviations (id bigserial PRIMARY KEY, site_code text, patient_ref text, category text, occurred date);
CREATE TABLE ctms.monitoring_visits (id bigserial PRIMARY KEY, site_code text, visit_date date, type text, notes text);
CREATE TABLE ctms.screening (id bigserial PRIMARY KEY, site_code text, screened date, outcome text, fail_reason text);
CREATE TABLE irt.kits (kit_no text PRIMARY KEY, patient_ref text, dispensed date);
CREATE TABLE unblinded.randomization (patient_ref text PRIMARY KEY, arm text NOT NULL, randomized date);
