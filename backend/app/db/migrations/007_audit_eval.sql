CREATE TABLE audit.log (ts timestamptz NOT NULL DEFAULT now(), sim_date date, actor text, role text,
  action text, entity text, entity_id text, payload jsonb);
SELECT create_hypertable('audit.log', by_range('ts'));
CREATE TABLE answer_key.site_personality (site_id text PRIMARY KEY, personality text);
CREATE TABLE answer_key.planted (id bigserial PRIMARY KEY, scenario_run_id uuid, kind text, module text,
  usubjid text, site_id text, src_table text, src_pk text, field text, original text, injected text);
CREATE TABLE answer_key.causality_reference (case_id text PRIMARY KEY, category text, rule_trace jsonb);
CREATE TABLE answer_key.crosswalk_truth (system text, source_id text, canonical_id text, PRIMARY KEY (system, source_id));
CREATE TABLE answer_key.eligibility_qa (id int PRIMARY KEY, question text, expected_answer text,
  expected_quote text, should_escalate bool);
CREATE TABLE eval.scenario_runs (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), scenario text, seed int,
  fork_name text, fork_seconds real, model text, prompt_version text, status text,
  started_at timestamptz DEFAULT now(), finished_at timestamptz);
CREATE TABLE eval.metrics (ts timestamptz NOT NULL DEFAULT now(), scenario_run_id uuid, module text,
  metric text, value double precision, detail jsonb);
SELECT create_hypertable('eval.metrics', by_range('ts'));
