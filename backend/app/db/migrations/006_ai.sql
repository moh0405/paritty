CREATE TABLE ai.ae_terms (id bigserial PRIMARY KEY, term text NOT NULL, coded_term text NOT NULL,
  source text, embedding vector(768));
CREATE INDEX ae_terms_bm25 ON ai.ae_terms USING bm25 (term) WITH (text_config='english');
CREATE INDEX ae_terms_vec ON ai.ae_terms USING diskann (embedding vector_cosine_ops);
CREATE TABLE ai.protocol_chunks (id bigserial PRIMARY KEY, section text, text text NOT NULL,
  is_synthetic bool, embedding vector(768));
CREATE INDEX protocol_bm25 ON ai.protocol_chunks USING bm25 (text) WITH (text_config='english');
CREATE INDEX protocol_vec ON ai.protocol_chunks USING diskann (embedding vector_cosine_ops);
CREATE TABLE ai.findings (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_ref text, module text,
  rule_id text, severity text, usubjid text, site_id text, title text, body jsonb,
  verification_status text, review_status text DEFAULT 'open', reviewer_note text,
  sim_date date, created_at timestamptz DEFAULT now());
CREATE TABLE ai.citations (id bigserial PRIMARY KEY, finding_id uuid, draft_id uuid, claim_idx int,
  src_table text, src_pk text, src_column text, cited_value text, quote text);
CREATE TABLE ai.verifications (id bigserial PRIMARY KEY, finding_id uuid, draft_id uuid, claim_idx int,
  check_name text, passed bool, detail text, checked_at timestamptz DEFAULT now());
CREATE TABLE ai.term_decisions (term_a text, term_b text, same_event bool, confidence real,
  method text, reason text, PRIMARY KEY (term_a, term_b));
CREATE TABLE ai.causality_assessments (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), case_id text,
  usubjid text, category text, confidence real, escalate bool, body jsonb, verification_status text,
  created_at timestamptz DEFAULT now());
CREATE TABLE ai.llm_calls (ts timestamptz NOT NULL DEFAULT now(), job text, model text,
  prompt_version text, cache_hit bool, input_tokens int, output_tokens int, latency_ms int, ok bool);
SELECT create_hypertable('ai.llm_calls', by_range('ts'));
