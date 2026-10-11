CREATE TABLE edc.sites (site_id text PRIMARY KEY, name text, is_synthetic bool);
CREATE TABLE edc.subjects (usubjid text PRIMARY KEY, site_id text NOT NULL REFERENCES edc.sites,
  age int, sex text, consent_at date, first_dose_at date, discontinued_at date, death_at date,
  status text, is_synthetic bool, entered_at date NOT NULL);
CREATE TABLE edc.ae (id bigserial PRIMARY KEY, usubjid text NOT NULL, site_id text NOT NULL,
  source_seq int, term_verbatim text, term_coded text, onset_at date, end_at date,
  date_imputed bool DEFAULT false, serious bool, severity text, ctcae_grade int,
  causality text, outcome text, augmented bool DEFAULT false,
  entered_at date NOT NULL, updated_at timestamptz DEFAULT now());
CREATE TABLE edc.lab (id bigserial, usubjid text NOT NULL, site_id text NOT NULL, test_code text NOT NULL,
  value double precision, unit text, uln double precision, lln double precision, x_uln double precision,
  ctcae_grade int, visit text, source_seq int, collected_at timestamptz NOT NULL, entered_at date NOT NULL,
  PRIMARY KEY (id, collected_at));
SELECT create_hypertable('edc.lab', by_range('collected_at', INTERVAL '30 days'));
CREATE INDEX ON edc.lab (usubjid, test_code, collected_at DESC);
CREATE TABLE edc.vitals (id bigserial, usubjid text NOT NULL, site_id text NOT NULL, test_code text NOT NULL,
  value double precision, unit text, visit text, measured_at timestamptz NOT NULL, entered_at date NOT NULL,
  PRIMARY KEY (id, measured_at));
SELECT create_hypertable('edc.vitals', by_range('measured_at', INTERVAL '30 days'));
CREATE TABLE edc.visits (id bigserial PRIMARY KEY, usubjid text, site_id text, visit text,
  planned_day int, actual_date date, entered_at date NOT NULL);
CREATE TABLE edc.exposure (id bigserial PRIMARY KEY, usubjid text, site_id text, dose double precision,
  start_at date, end_at date, entered_at date NOT NULL);
CREATE TABLE edc.conmeds (id bigserial PRIMARY KEY, usubjid text, site_id text, term text,
  start_at date, end_at date, entered_at date NOT NULL);
CREATE TABLE edc.medical_history (id bigserial PRIMARY KEY, usubjid text, term text);

-- Staging: generated rows wait here until entered_at <= sim today (ingestor moves them to edc.*).
CREATE TABLE edc_pending.sites (LIKE edc.sites INCLUDING DEFAULTS);
CREATE TABLE edc_pending.subjects (LIKE edc.subjects INCLUDING DEFAULTS);
CREATE TABLE edc_pending.ae (LIKE edc.ae INCLUDING DEFAULTS);
CREATE TABLE edc_pending.lab (LIKE edc.lab INCLUDING DEFAULTS);
CREATE TABLE edc_pending.vitals (LIKE edc.vitals INCLUDING DEFAULTS);
CREATE TABLE edc_pending.visits (LIKE edc.visits INCLUDING DEFAULTS);
CREATE TABLE edc_pending.exposure (LIKE edc.exposure INCLUDING DEFAULTS);
CREATE TABLE edc_pending.conmeds (LIKE edc.conmeds INCLUDING DEFAULTS);
CREATE TABLE edc_pending.medical_history (LIKE edc.medical_history INCLUDING DEFAULTS);
