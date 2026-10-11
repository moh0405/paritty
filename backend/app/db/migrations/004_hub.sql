CREATE TABLE hub.site_xwalk (canonical_site text, system text, source_id text, confidence real,
  method text, status text DEFAULT 'proposed', confirmed_by text, PRIMARY KEY (system, source_id));
CREATE TABLE hub.subject_xwalk (canonical_subject text, system text, source_id text, confidence real,
  method text, status text DEFAULT 'proposed', confirmed_by text, PRIMARY KEY (system, source_id));
CREATE TABLE hub.catalog (table_name text PRIMARY KEY, description text, owner text, refresh text,
  sensitivity text, last_loaded timestamptz, row_count bigint);
CREATE INDEX catalog_bm25 ON hub.catalog USING bm25 (description) WITH (text_config='english');
CREATE TABLE hub.dq_results (ts timestamptz NOT NULL DEFAULT now(), sim_date date, rule text,
  table_name text, dimension text, failed_rows int, sample_pks text[]);
SELECT create_hypertable('hub.dq_results', by_range('ts'));

-- Role-safe views (no treatment arm anywhere).
CREATE VIEW hub.v_sites AS SELECT site_id, name, is_synthetic FROM edc.sites;
CREATE VIEW hub.v_subjects AS SELECT usubjid, site_id, age, sex, consent_at, first_dose_at, discontinued_at, death_at, status FROM edc.subjects;
CREATE VIEW hub.v_site_summary AS
  SELECT s.site_id, s.name, count(DISTINCT u.usubjid) AS subjects
  FROM edc.sites s LEFT JOIN edc.subjects u USING (site_id) GROUP BY s.site_id, s.name;
