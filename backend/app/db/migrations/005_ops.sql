CREATE TABLE ops.sim_clock (id int PRIMARY KEY DEFAULT 1, today date NOT NULL, study_start date NOT NULL);
CREATE TABLE ops.check_specs (id text PRIMARY KEY, type text NOT NULL, params jsonb NOT NULL,
  ctq_category text, severity text, source text, approval_status text, approved_by text,
  approved_at timestamptz, rationale jsonb, active bool DEFAULT true);
CREATE TABLE ops.check_failures (id bigserial PRIMARY KEY, check_id text, usubjid text, site_id text,
  src_table text, src_pk text, observed text, expected text, detected_on date, resolved_on date,
  UNIQUE (check_id, src_table, src_pk));
CREATE TABLE ops.queries (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), failure_id bigint, finding_id uuid,
  site_id text, usubjid text, priority real, state text NOT NULL, text text, language text DEFAULT 'en',
  opened_on date, sent_on date, answered_on date, closed_on date, reopen_count int DEFAULT 0,
  approved_by text, closed_reason text);
CREATE TABLE ops.query_events (ts timestamptz NOT NULL DEFAULT now(), sim_date date, query_id uuid,
  site_id text, event text, actor text, detail jsonb);
SELECT create_hypertable('ops.query_events', by_range('ts'));
CREATE TABLE ops.site_responses (id bigserial PRIMARY KEY, query_id uuid, due_on date, kind text,
  payload jsonb, delivered bool DEFAULT false);
CREATE TABLE ops.digests (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), site_id text, week_of date,
  query_ids uuid[], text text, state text);
CREATE TABLE ops.kri_values (sim_date date NOT NULL, site_id text, kri text, value double precision,
  comparator double precision, rag text, PRIMARY KEY (sim_date, site_id, kri));
SELECT create_hypertable('ops.kri_values', by_range('sim_date', INTERVAL '30 days'));
CREATE TABLE ops.site_risk (sim_date date NOT NULL, site_id text, rule_score real, model_score real,
  signals jsonb, PRIMARY KEY (sim_date, site_id));
SELECT create_hypertable('ops.site_risk', by_range('sim_date', INTERVAL '30 days'));
CREATE TABLE ops.lock_forecasts (sim_date date NOT NULL PRIMARY KEY, p10 date, p50 date, p90 date,
  readiness jsonb, blockers jsonb, n_sims int);
SELECT create_hypertable('ops.lock_forecasts', by_range('sim_date', INTERVAL '90 days'));
CREATE TABLE ops.issues (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), site_id text, source text,
  title text, status text, owner text, opened date, closed date, links jsonb);
CREATE TABLE ops.drafts (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), kind text,
  subject_ref text, site_id text, body jsonb, state text DEFAULT 'draft', approved_by text,
  approved_at timestamptz, created_at timestamptz DEFAULT now());
CREATE TABLE ops.escalations (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), usubjid text, finding_id uuid,
  reason text, raised_by text, raised_at timestamptz DEFAULT now(), status text, resolution text);
