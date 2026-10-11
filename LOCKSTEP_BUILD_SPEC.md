# Paritty — Build Spec

Continuous clean-to-lock copilot for clinical trials. Built for HackRU 2026 (Regeneron challenge + MLH Best Use of Gemini + Best Use of Tiger Data).

## 0. How to use this spec (for Claude Code)

- Build in the milestone order in §17. Finish a milestone's "done when" checks before starting the next.
- Everything must run from a clean clone via the Makefile (§15). Never require manual DB edits.
- Section §18 lists facts that were **not verified** when this spec was written (CLI flags, extension availability, dataset contents). Check them before relying on them; adapt and note the change in `docs/DECISIONS.md`.
- Keep the code typed (Pydantic v2, type hints, TypeScript strict). Small classes, one responsibility each. Tests for core logic (§16).
- When a choice is ambiguous, prefer: deterministic over LLM, simple over clever, working end to end over complete.

## 1. Product summary

Paritty simulates a running multi-site trial and cleans its data continuously so the database can lock sooner. A trial clock releases data daily; edit checks run on new data; failures become prioritized query drafts a human approves; a simulated site answers; queries auto-close or reopen. Safety (SAE) and central-lab data are reconciled against the EDC. Medical signals (Hy's Law etc.) and site risks are flagged. A Monte Carlo forecast predicts the lock date with blockers. Every AI-written claim cites source rows and is verified by code. An eval harness on database forks measures accuracy against answer keys.

Regeneron starter sheets covered (their numbering) and target tier:

| Sheet | Target |
|---|---|
| #10 Clean Sweep (anchor) | Best: 20–30 edit checks; protocol-generated checks with approval; CTQ ranking; query aging; daily batches; auto open/close; external lab reconciliation; lock forecast with range + blockers |
| #18b Two Databases, One Truth | Best: fuzzy matcher; acceptable vs actionable; drafted queries; resolution dashboard; follow-up versions; mock EDC → E2B-style message → mock safety API; audit trail |
| #08 Hidden in the Labs | Best: patient profiles; CTCAE flags; eDISH; site/visit trends; AE-lab linking; review notes; eligibility assistant with protocol citations + escalate; escalation log; blinding enforced |
| #04 Check Engine Light | Best: 8 KRIs with RAG; cross-site anomaly tests; precision/recall on planted sites; visit plan, agenda, follow-up letters; issue tracking; site concierge (protocol Q&A) |
| #40 One Source of Truth | Best: mock feeds with mismatched IDs; crosswalk; catalog; lineage; data-quality dashboard; NL questions → SQL with lineage; role-based access on every answer |
| Extra (AE Causality) | Causality assessment with cited evidence, confidence and escalation, inside SAE reconciliation |

## 2. Non-negotiable rules

1. Public or synthetic data only. Cite every source in `README.md` and `DATA.md`. CDISC pilot data is educational-use licensed.
2. **Humans approve** every generated edit check, query, correction, review note, letter, agenda, eligibility answer and agent action before it takes effect or "leaves" the system. Store `approved_by` and timestamp.
3. **Blinding:** treatment arm lives only in `unblinded.randomization`. Only role `unblinded_statistician` can read it. Default UI is blinded. Unblinded views show a red banner and are audit-logged. Gemini never receives arm data. eDISH and all charts are never colored by arm in blinded mode.
4. The tool never diagnoses or accuses. UI wording: "potential", "needs review", "reason to look". Never "fraud", "misconduct", "diagnosis".
5. Gemini never produces executable logic. It returns JSON specs (checks) or SQL (NL ask) that our code validates; NL SQL runs read-only under the caller's role with a statement timeout.
6. Detection is deterministic (rules/statistics/ML). Gemini explains, drafts, adjudicates. Every Gemini claim must carry citations and pass the verifier (§11) or be blocked.
7. Detector and app code must never read the `answer_key` schema. Enforce with DB roles: the app connects as roles without access; only the eval scorer uses `eval_admin`.
8. Every state change writes to `audit.log`.

## 3. Stack

- **DB:** Tiger Cloud Postgres (PG 17+) with `timescaledb`, `vectorscale` (pgvectorscale; pulls in `vector`), `pg_textsearch` (BM25). Postgres roles + row-level security. Local fallback: Docker `timescale/timescaledb-ha` image (check which of these extensions it ships; fall back per §18).
- **Backend:** Python 3.12, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2 Core + psycopg 3 (pool), pandas, pyarrow, numpy, scipy, scikit-learn, lifelines, rapidfuzz, pyyaml, pyreadr, requests, google-genai, sse-starlette, reportlab (PDF exports), pytest. Dependency manager: `uv`.
- **AI:** Gemini via `google-genai`. Models from env: `GEMINI_FAST_MODEL=gemini-flash-latest`, `GEMINI_STRONG_MODEL=<current Pro>`, `GEMINI_EMBED_MODEL=gemini-embedding-2`, `EMBED_DIM=768`. Do not use gemini-2.5-* (shut down 2026-10-16).
- **Frontend:** Next.js (App Router) + TypeScript strict + Tailwind + shadcn/ui + TanStack Query + Recharts. Typed client generated from FastAPI OpenAPI (`openapi-typescript`).
- **Forks:** Tiger CLI (`tiger`) via subprocess; fallback `CREATE DATABASE ... TEMPLATE golden`.

## 4. Repository layout

```
lockstep/
├── Makefile · docker-compose.yml · .env.example
├── README.md · DATA.md · docs/DECISIONS.md
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py · config.py · deps.py
│   │   ├── db/          connection.py · roles.py · migrations/NNN_*.sql · migrate.py · repositories/
│   │   ├── domain/      models.py · enums.py
│   │   ├── sim/         clock.py · daily_cycle.py · ingestor.py · site_responder.py · personalities.py
│   │   ├── checks/      base.py · library.py · dsl.py · factory.py · generator.py · effectiveness.py
│   │   ├── queries/     lifecycle.py · prioritizer.py · digest.py · aging.py · translate.py
│   │   ├── recon/       labs.py · sae/{matcher,classifier,causality,e2b_mapper,mock_safety_api}.py
│   │   ├── medical/     ctcae.py · hys_law.py · trends.py · clusters.py · ae_lab_links.py · profiles.py · notes.py · escalations.py
│   │   ├── sites/       kris.py · anomaly.py · risk_model.py · scorer.py · visit_planner.py · letters.py · issues.py · scorecard_pdf.py
│   │   ├── forecast/    readiness.py · montecarlo.py · blockers.py · whatif.py · backtest.py
│   │   ├── agent/       data_manager.py · tools.py
│   │   ├── hub/         adapters/ · crosswalk.py · catalog.py · lineage.py · dq.py · questions.py · ask.py
│   │   ├── protocol/    chunker.py · qa_engine.py
│   │   ├── llm/         client.py · gemini.py · replay.py · cache.py · schemas.py · prompts/*.md
│   │   ├── search/      terms.py · hybrid.py
│   │   ├── verification/ verifier.py · checks.py · normalize.py
│   │   ├── evals/       fork_manager.py · injectors/ · scenarios.py · scorer.py · harness.py · report.py
│   │   ├── exports/     csv.py · signal_pack.py
│   │   ├── audit/       logger.py
│   │   └── api/         routers/*.py
│   ├── scripts/         download_data.py · build_golden.py · scale_sites.py · build_mock_systems.py
│   │                    plant_baseline.py · build_protocol.py · seed_search.py · train_risk_model.py
│   ├── scenarios/       smoke.yaml · full.yaml · sites.yaml · forecast_backtest.yaml
│   ├── fixtures/llm_cache/      # committed Gemini responses (replay mode)
│   └── tests/
├── data/raw/ (gitignored) · data/protocol/ (committed synthetic protocol + eligibility emails)
└── frontend/ (Next.js app, §14)
```

## 5. Environment (`.env.example`)

```
DATABASE_URL=postgresql://app_admin:...@host:port/tsdb?sslmode=require
EVAL_ADMIN_URL=postgresql://eval_admin:...@host:port/tsdb?sslmode=require
GOLDEN_SERVICE_ID=
FORK_BACKEND=tiger            # tiger | template
LLM_MODE=replay               # live | replay | record
GEMINI_API_KEY=
GEMINI_FAST_MODEL=gemini-flash-latest
GEMINI_STRONG_MODEL=
GEMINI_EMBED_MODEL=gemini-embedding-2
EMBED_DIM=768
SEED=42
SIM_START_DAY=60
```

`LLM_MODE=replay` serves responses from `fixtures/llm_cache`; a cache miss in replay mode returns a clearly labeled stub and logs a warning. `record` calls Gemini and writes to the cache.

## 6. Data acquisition (`scripts/download_data.py`)

- CDISC pilot SDTM `.xpt` files from `https://github.com/cdisc-org/sdtm-adam-pilot-project/raw/master/updated-pilot-submission-package/900172/m5/datasets/cdiscpilot01/tabulations/sdtm/{dom}.xpt` for `dm ae lb vs ex ds sv cm tv ta suppae`. Read with `pandas.read_sas(BytesIO, format="xport", encoding="latin-1")`; save to `data/raw/{dom}.parquet`. Missing optional domains: log and continue. Required: dm, ae, lb, vs.
- Optional: prefer pharmaversesdtm updated `ae`/`lb` (`.rda` from github.com/pharmaverse/pharmaversesdtm, read with `pyreadr`) when available.
- ClinicalTrials.gov API v2: fetch one Alzheimer's interventional study JSON (`https://clinicaltrials.gov/api/v2/studies/{NCT}`), save to `data/raw/ctgov_study.json`. Use its eligibility criteria and locations.
- openFDA: fetch `https://api.fda.gov/drug/event.json?limit=5` once to copy field structure into `data/raw/openfda_sample.json` (structure reference only).
- CTCAE grading thresholds: hand-encode the needed lab rows (ALT, AST, bilirubin, ALP, creatinine, hemoglobin, platelets, neutrophils) in `medical/ctcae.py` with a source comment; confirm against the current NCI CTCAE file.
- If downloads fail in a sandbox, the script prints the URLs and the expected file paths so a human can place them.

## 7. Simulation (golden database build)

All generators take `SEED` and are deterministic. Write `DATA.md` documenting each step.

### 7.1 Normalize EDC (`build_golden.py`)
- ISO-8601 strings → dates/timestamps. Partial dates: impute day 1 / month Jan, set `date_imputed=true`. Undated lab/vital rows are excluded from hypertables and logged.
- Denormalize `site_id` onto AE/LB/VS rows. Compute `x_uln = value/uln`, CTCAE grade.
- Consent date: use `DM.RFICDTC` if present, else first visit minus U(0,14) days.
- Assign `entered_at` per row = event date + site entry lag (from personality, §7.2).
- Sim calendar: shift all dates so the study runs from a fixed start; set `ops.sim_clock.today = study_start + SIM_START_DAY`.

### 7.2 Scale sites (`scale_sites.py`)
- Clone pilot subjects into synthetic sites to reach 24 sites total: new IDs (`01-9XX-NNNN`), per-site date offset, multiplicative noise ~3% on labs/vitals, `is_synthetic=true`.
- Fictional site names and cities (never real hospitals).
- Personalities (2 sites each, rest `normal`), stored only in `answer_key.site_personality`:
  - `under_reporter`: delete ~60% non-serious AEs.
  - `sloppy_entry`: entry lag 10–25 days; 3× edit-check error rate.
  - `too_perfect`: round 70% of BP to multiples of 5/10; shrink pulse within-subject SD to 30%; copy one vitals panel across 3 subjects.
  - `rule_bender`: 25% visits outside window; eligibility values within 5% of cutoffs.
  - `slow_responder`: query response lognormal mean 20 days, 20% wrong corrections.
  - `normal`: response lognormal mean 5 days, 5% wrong corrections, lag 1–5 days.

### 7.3 Mock systems (`build_mock_systems.py`)
| System | Table | Quirks |
|---|---|---|
| Central lab | `lab_vendor.transfer` | `patient_ref='PT701-1015'`, DD/MM/YYYY strings, test names spelled out, some SI vs conventional units (bilirubin µmol/L), one file per sim day |
| Safety DB | `safety.case_versions` | openFDA/E2B-shaped `payload` JSON (`safetyreportid`, `receivedate` YYYYMMDD, `serious`, `seriousnessdeath/hospitalization/...`, `patient.reaction[{reactionmeddrapt, reactionoutcome 1–6}]`, `patient.drug[...]`), plus `causality` (Related/Not related), `subject_ref='SUBJ 1015 / SITE 701'`, Gemini-generated `narrative` (record once, cache) |
| CTMS | `ctms.sites`, `ctms.deviations`, `ctms.monitoring_visits`, `ctms.screening` | `site_code='SITE-0701'`, name spelling variants, one duplicate site record, one site with no EDC patients |
| IRT | `irt.kits`, `unblinded.randomization` | `patient_ref='R-701-015'`; arm only in `unblinded` |

- Safety case set: all EDC AEs with `serious=true`. If fewer than 40, promote severe AEs to serious (deterministic by seed), flag `augmented=true`.
- ~20% of safety cases get a v2 a few sim days later (outcome update / added detail).
- Causality reference labels: for every safety case, compute a deterministic simplified WHO-UMC category (certain/probable/possible/unlikely) from: onset after first dose, time-to-onset plausibility, dechallenge (event resolved after drug stopped, from EX/AE end dates), alternative cause present (from MH/CM). Store in `answer_key.causality_reference` with the rule trace.

### 7.4 Baseline problems (`plant_baseline.py`)
Planted into the golden DB so the demo has realistic mess; each one recorded in `answer_key.planted` (`id, kind, module, usubjid, site_id, src_table, src_pk, field, original, injected`):
- Edit-check errors (~150): impossible values, wrong date order, AE end before start, lb/kg mix-up, °F as °C, missing visits, duplicates, missing required fields — distributed by site personality.
- Lab vendor mismatches (~25): value, unit, date, missing either side; one stale feed (no files for 10 sim days).
- SAE discrepancies (~30): shifted onset (±1 and >1 day), synonym terms (should be acceptable), coded-term changes, causality flips, seriousness flips, missing outcome, EDC-only, safety-only, one death mismatch.
- Medical signals: 3 Hy's Law patients (ALT ~5×, bili ~3× within 14 days), one site ALT creep (+8%/visit), one rare-AE cluster (4 cases at one site), 6 AE–lab co-occurrences.
- Hub quality: duplicate records, orphan kits, randomization after first dose, impossible dates.

**Blind planting:** eval scenarios (§12) plant *additional* errors at random with a seed chosen at run time and stored only in `answer_key`/`eval` schemas. Builders must not hand-tune detectors to specific planted rows.

### 7.5 Protocol (`build_protocol.py`)
- `data/protocol/protocol.md`: real eligibility criteria from the CT.gov study + a **synthetic** protocol summary modeled on the pilot (visit schedule with windows, e.g. "Week 8 (Day 56 ± 7 days)", dosing, prohibited meds, liver stopping rules). Mark synthetic sections clearly.
- `data/protocol/eligibility_emails.jsonl`: 40 site questions with `expected_answer`, `expected_quote`, `should_escalate`.
- Chunk by heading (~150–300 words), embed, load into `ai.protocol_chunks`.

### 7.6 Search seed (`seed_search.py`)
- `ai.ae_terms`: distinct AEDECOD + AETERM variants + a small synonym list (`data/protocol/ae_synonyms.csv`, e.g. heart attack ↔ myocardial infarction), embedded.
- `hub.catalog` rows for every table.

## 8. Database schema

Migrations in `backend/app/db/migrations/`, applied in order by `migrate.py`. Hypertable unique keys must include the time column.

```sql
-- 001_extensions_schemas.sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;
CREATE EXTENSION IF NOT EXISTS pg_textsearch;
CREATE SCHEMA edc; CREATE SCHEMA lab_vendor; CREATE SCHEMA safety; CREATE SCHEMA mock_safety;
CREATE SCHEMA ctms; CREATE SCHEMA irt; CREATE SCHEMA unblinded; CREATE SCHEMA hub;
CREATE SCHEMA ops; CREATE SCHEMA ai; CREATE SCHEMA audit; CREATE SCHEMA eval; CREATE SCHEMA answer_key;

-- 002_edc.sql
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
-- Staging: everything generated lives in edc_pending.* with the same columns; the ingestor
-- moves rows into edc.* when entered_at <= sim today. (CREATE TABLE edc_pending.X (LIKE edc.X INCLUDING ALL))

-- 003_external.sql
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

-- 004_hub.sql
CREATE TABLE hub.site_xwalk (canonical_site text, system text, source_id text, confidence real,
  method text, status text DEFAULT 'proposed', confirmed_by text, PRIMARY KEY (system, source_id));
CREATE TABLE hub.subject_xwalk (canonical_subject text, system text, source_id text, confidence real,
  method text, status text DEFAULT 'proposed', confirmed_by text, PRIMARY KEY (system, source_id));
CREATE TABLE hub.catalog (table_name text PRIMARY KEY, description text, owner text, refresh text,
  sensitivity text, last_loaded timestamptz, row_count bigint);
CREATE INDEX ON hub.catalog USING bm25 (description) WITH (text_config='english');
CREATE TABLE hub.dq_results (ts timestamptz NOT NULL DEFAULT now(), sim_date date, rule text,
  table_name text, dimension text, failed_rows int, sample_pks text[]);
SELECT create_hypertable('hub.dq_results', by_range('ts'));
-- Role-safe views used by NL ask and cross-system questions:
-- hub.v_sites, hub.v_subjects (no arm), hub.v_site_summary (aggregates only), hub.v_open_items

-- 005_ops.sql
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
CREATE TABLE ops.drafts (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), kind text, -- note|letter|agenda|eligibility|agent_action
  subject_ref text, site_id text, body jsonb, state text DEFAULT 'draft', approved_by text,
  approved_at timestamptz, created_at timestamptz DEFAULT now());
CREATE TABLE ops.escalations (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), usubjid text, finding_id uuid,
  reason text, raised_by text, raised_at timestamptz DEFAULT now(), status text, resolution text);

-- 006_ai.sql
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

-- 007_audit_eval.sql
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

-- 008_aggregates.sql
CREATE MATERIALIZED VIEW ops.query_aging_daily WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', ts) AS day, site_id,
  count(*) FILTER (WHERE event='opened') AS opened, count(*) FILTER (WHERE event='closed') AS closed,
  count(*) FILTER (WHERE event='reopened') AS reopened
FROM ops.query_events GROUP BY day, site_id WITH NO DATA;
CREATE MATERIALIZED VIEW edc.site_vitals_weekly WITH (timescaledb.continuous) AS
SELECT site_id, test_code, time_bucket('7 days', measured_at) AS bucket, count(*) AS n,
  avg(value) AS mean, stddev_samp(value) AS sd,
  count(*) FILTER (WHERE value::int % 10 = 0) AS ends0, count(*) FILTER (WHERE value::int % 5 = 0) AS ends05
FROM edc.vitals GROUP BY site_id, test_code, bucket WITH NO DATA;
-- Refresh both at the end of each daily cycle: CALL refresh_continuous_aggregate(...)

-- 009_roles.sql
-- app roles: data_manager, medical_monitor, central_monitor, study_lead, unblinded_statistician
-- app_admin (migrations/seed), eval_admin (scorer only; reads answer_key)
-- REVOKE ALL ON SCHEMA unblinded, answer_key FROM PUBLIC;
-- GRANT USAGE/SELECT on unblinded to unblinded_statistician only; answer_key to eval_admin only.
-- study_lead: SELECT only on hub.v_site_summary and aggregate views (no patient-level tables).
-- RLS on edc.ae, edc.lab, edc.vitals, edc.subjects:
--   USING (current_setting('app.site_scope', true) IS NULL OR site_id = ANY(string_to_array(current_setting('app.site_scope', true), ',')))
-- Backend sets per request inside a transaction: SET LOCAL ROLE <role>; SET LOCAL app.site_scope = '...';
```

## 9. Backend modules

Each module: classes, algorithm, and acceptance criteria. Patterns: Strategy (checks, KRIs, signals, injectors, LLM clients, fork managers), Template Method (run loops), Registry (lookup by name), State (query lifecycle), Repository (SQL), Observer (audit, auto-close), Adapter (feeds).

### 9.1 Trial clock and daily cycle (`sim/`)
- `TrialClock.today()`, `advance(days)`; each day runs `DailyCycle.run(day)`:
  1. **Ingest**: move `edc_pending.*` rows with `entered_at <= day` into `edc.*`; release `lab_vendor.transfer` files with `file_date <= day` (skip for stale feed); make `safety.case_versions` with `available_on <= day` visible; deliver due `ops.site_responses` (apply corrections to EDC rows).
  2. **Check**: run edit checks incrementally on the day's `ChangeSet` (inserted/updated row ids per table).
  3. **Queries**: new failures → draft queries; for open queries whose source row changed, re-run the check → auto-close or reopen.
  4. **Reconcile**: lab recon and SAE recon for affected subjects.
  5. **Signals**: medical signals, KRIs, anomaly tests, risk scores; refresh continuous aggregates; DQ rules.
  6. **Forecast**: readiness + Monte Carlo; store snapshot.
  7. **Agent** (if enabled): data-manager agent proposes actions (drafts only).
  8. **Audit**.
- `SiteResponder`: when a query is `Sent`, schedule a response by personality: `correct` (fix value so check passes), `explain` (no data change; DM must close with explanation), `wrong_correction` (change value, check still fails).
- Done when: `POST /sim/advance {days:30}` runs in < 60 s and produces new data, failures, queries, responses, closes and reopens visible in the API.

### 9.2 Edit checks (`checks/`)
- `EditCheckSpec` types: `range`, `unit_plausibility`, `date_order`, `required_field`, `visit_window`, `missing_visit`, `duplicate`, `cross_form`, `external_lab`. `CheckFactory` compiles spec → parameterized SQL over an allow-list of tables/columns. Unknown table/column → reject.
- Library (`library.py`), 26 checks:
  1–6 range: SBP 60–250, DBP 30–150, pulse 30–200, temp 34–42 °C, weight 30–250 kg, height 120–220 cm · 7 weight change >20% with ratio ≈2.2 (lb/kg) · 8 temp >45 (°F) · 9 AE end < start · 10 AE start < consent · 11 visit dates out of order · 12 any date after death/discontinuation · 13 date in future vs sim today · 14 exposure end < start · 15 serious AE missing seriousness/severity/outcome · 16 lab missing unit or range · 17 missing scheduled visit past window · 18 visit outside window · 19 duplicate lab/vitals · 20 duplicate AE · 21 dosing after discontinuation · 22 serious EDC AE with no safety case · 23 ALT/AST ≥3×ULN without hepatic AE ±14 d · 24 central-lab value ≠ EDC (>1% rel) · 25 one-sided lab record · 26 lab unit mismatch.
- `CheckGenerator`: Gemini reads protocol chunks → `EditCheckSpec[]` with `rationale.quote` + `chunk_id`. Validate (Pydantic + factory compile + quote verification) → dry-run count → `pending_approval`. Only `approved` specs run.
- `CheckEffectiveness`: per check, true positives vs false alarms against `answer_key.planted` (eval-only view) and in-app "confirmed vs dismissed" counts; recommend retiring checks with high false-alarm rate.
- Done when: library catches ≥80% of planted edit-check errors on the golden build with a false-alarm rate reported; a generated check can be approved and then fires on the next cycle.

### 9.3 Queries (`queries/`)
- States: `Draft → Approved → Sent → Answered → Closed | Reopened | ClosedWithExplanation`. Transitions only via State classes; each writes `ops.query_events`.
- Drafting: Gemini writes query text from the failure + source rows (specific values, specific ask). Fallback template if replay miss.
- `QueryPrioritizer`: `priority = w_ctq × w_sev × w_age × w_site`; CTQ: safety 1.0, efficacy 0.8, eligibility 0.7, other 0.3; severity: critical 1.0, major 0.6, minor 0.2; age `min(3, 1 + days_open/14)`; site: amber 1.2, red 1.5.
- `MinorIssueDigest`: queries with priority < 0.15 grouped weekly per site into one digest draft.
- `QueryTranslator`: draft in site language (CTMS site language field); verify every number/date in the source text appears in the translation; block on mismatch.
- Aging buckets 0–7, 8–14, 15–30, >30 days by site from the continuous aggregate.
- Done when: full lifecycle visible in UI; wrong corrections reopen; aging by site renders.

### 9.4 External lab reconciliation (`recon/labs.py`)
- Map `patient_ref` via subject crosswalk; parse DD/MM/YYYY; test name → test code map; unit conversion (bilirubin µmol/L ÷ 17.1 = mg/dL; ALT/AST U/L both sides).
- Match (subject, test, date ±1 d). Classify: value mismatch (>1% rel), unit mismatch, EDC-only, vendor-only. Stale feed if no file > 3 expected days.
- Done when: planted lab mismatches recall ≥90%.

### 9.5 SAE reconciliation (`recon/sae/`)
- `SaeMatcher`: per subject, score = 0.6·term_sim + 0.4·max(0, 1 − |Δdays|/30); `scipy.optimize.linear_sum_assignment`; reject < 0.35. Compare against latest case version.
- `HybridTermMatcher`: exact coded match → 1.0; else BM25 + vector RRF on `ai.ae_terms`; 0.5–0.8 grey zone → Gemini adjudication cached in `ai.term_decisions`.
- `DiscrepancyClassifier` rules:

| Difference | Class |
|---|---|
| onset Δ ≤ 1 day | acceptable |
| onset Δ > 1 day | actionable |
| different wording, same coded term | acceptable |
| different coded term | actionable |
| seriousness / criteria differ | actionable |
| causality differs (EDC PROBABLE/POSSIBLE→Related, REMOTE/NONE→Not related) | actionable → triggers causality assessment |
| outcome differs, safety newer with follow-up | acceptable; else actionable |
| outcome missing either side | actionable |
| death on one side only | critical |
| case on one side only | actionable (critical if fatal) |
| safety has extra narrative detail | acceptable |

- `CausalityAssessor` (extra): for causality conflicts and on demand, give Gemini the case narrative, dosing (EX), AE dates, labs ±30 d, conmeds, medical history. Output `{category: certain|probable|possible|unlikely|unassessable, confidence, evidence[{claim, citations}], alternative_causes[], escalate}`. Verify citations. Escalate if confidence < 0.6 or verification partial. Eval vs `answer_key.causality_reference` (agreement, Cohen's kappa).
- `E2BMapper` + `MockSafetyApi`: on new serious EDC AE, build openFDA/E2B-shaped message → `POST /mock-safety/cases` → `mock_safety.inbox`; continuous recon treats inbox as another safety source; follow-ups append versions.
- Done when: discrepancy precision and recall reported; synonyms classified acceptable; follow-up v2 changes reconciliation status.

### 9.6 Medical review (`medical/`)
- CTCAE grading per lab row; flags: ALT/AST ≥3×ULN, bili ≥2×ULN, grade ≥3 labs and AEs.
- `HysLawSignal`: peak ALT/AST ≥3× and bili ≥2× within 30 d; include ALP for context; wording "potential Hy's Law pattern — requires medical review".
- eDISH data: per subject peak ALT (and AST) ×ULN vs peak bili ×ULN, quadrant label.
- `SiteCreepSignal`: per site median of per-subject OLS slopes of x_uln vs study day; robust z vs sites; flag z > 3.
- `RareAeCluster`: terms with study rate < 1%; Poisson test of site count vs expected; flag p < 0.001 and count ≥ 3.
- `AeLabLink`: AE onset within ±7 d of a lab grade increase, same subject.
- Ranked review list: severity score (Hy's Law 100, grade 4 = 80, grade 3 = 60, creep/cluster 50, link 30) + recency.
- Patient profile payload: dosing, visits, AEs (grade), conmeds, lab series with ULN multiples, flags, links.
- Review notes: Gemini drafts from flagged rows → `ops.drafts(kind='note')` with citations; monitor signs.
- Escalation log; eligibility assistant via §9.10.
- Done when: all planted Hy's Law patients, creep site and cluster detected; blinded role sees no arm anywhere.

### 9.7 Site risk (`sites/`)
- KRIs (RAG red/amber):
  - AE rate per patient-month: < 0.5× or > 2× median / outside 0.67–1.5×
  - SAE rate per 100 patient-months: same bands
  - Query rate per 100 data points: > 2× / > 1.5× median
  - Median query resolution days: > 21 / > 14
  - Median entry lag days: > 14 / > 7
  - Deviations per patient: > 2× / > 1.5× median
  - Visit window violations: > 20% / > 10%
  - Screen-failure rate: robust z > 3 / > 2
- Anomaly tests: terminal-digit chi-square (BP last digit vs study), variance ratio < 0.5, duplicated vitals panels, AE under-reporting Poisson, visit-timing KS, borderline-eligibility share.
- Rule score: mean of capped (±4) robust z-scores → 0–100.
- `SiteRiskModel` (extra): `scripts/train_risk_model.py` simulates 600 synthetic site histories with random personalities (reuse §7.2 generators on cloned data, no DB needed), computes the same features, trains `HistGradientBoostingClassifier` (problem vs normal, plus multiclass personality). Save to `backend/models/site_risk.joblib`. Explain with permutation importance + per-site top contributing features. Compare against rule score in evals (precision@k, recall@k).
- Plain-English explanation per flag: data, comparison group, threshold, value.
- `VisitPlanner`: rank sites by risk × enrolled; action = visit (red), call (amber), remote (green with open issues); Gemini drafts agenda + follow-up letter with citations → `ops.drafts`; each approved item opens `ops.issues`.
- `ScorecardPdf`: one-page site scorecard via reportlab.
- Done when: planted problem sites in top-k with precision/recall reported for both rule and model scores.

### 9.8 Lock forecast (`forecast/`)
- Readiness criteria: all subjects final status; expected visits entered; zero open critical/major queries; SAE recon actionable = 0; lab recon clean; notes signed for flagged patients; generated checks decided.
- Remaining work: open items + expected future queries (site failure rate × remaining visits) + remaining visits from schedule.
- Resolution model: per-site Kaplan–Meier (`lifelines`) on query time-to-close (open = censored), shrunk toward pooled curve for sites with < 10 events.
- Monte Carlo (numpy vectorized, default 2000 sims): sample close times for each open/expected item; lock = max + 5-day lock procedure; P10/P50/P90.
- Blockers: leave-one-site-out and leave-one-category-out ΔP50; top 5.
- Benchmark: days from LPLV to P50 vs 36-day Tufts benchmark.
- `WhatIfRunner`: fork DB, apply `Hypothetical` (e.g. site X response mean = 3 d; recon closed), run forecast on fork, return both forecasts, delete fork.
- `Backtest`: fork at day N, forecast, advance fork to completion, record actual lock date, error.
- Done when: forecast updates daily; blockers explain movement; backtest error reported.

### 9.9 Data hub (`hub/`)
- Adapters load CTMS, IRT, lab vendor, safety into hub views.
- `CrosswalkBuilder`: normalize (strip prefixes, zero-pad, lowercase names) → exact → rapidfuzz (≥92 auto, 80–92 Gemini adjudication, < 80 unmatched for human) → `status='proposed'` until confirmed. Eval vs `answer_key.crosswalk_truth`.
- Catalog with BM25 search; freshness from `last_loaded`.
- Lineage: every finding/metric stores source query text + row refs; `GET /lineage/{entity}/{id}` returns the trail.
- DQ rules: completeness, validity, consistency, timeliness → `hub.dq_results`.
- Five fixed cross-system questions (`questions.py`): (1) sites with open critical queries AND unreconciled SAEs; (2) subjects dosed after discontinuation; (3) kits dispensed to discontinued subjects; (4) sites with red KRIs and no monitoring visit in 60 days; (5) subjects with Hy's Law pattern and open safety-case discrepancies.
- `AskService` (NL): Gemini → `{sql, explanation}` over allowed hub views only; reject non-SELECT, multiple statements, disallowed schemas; run under caller role with `statement_timeout=5s`, `LIMIT 500`; return SQL, rows, lineage; permission errors become "Your role can't see …".
- Done when: crosswalk precision/recall reported; the same question returns different results per role.

### 9.10 Protocol Q&A (`protocol/qa_engine.py`)
- Hybrid retrieve top 6 chunks (BM25 + vector RRF). Gemini → `{answer, quotes[{chunk_id, text}], escalate, confidence}`. Verify quotes are exact substrings. Escalate if no verified quote, confidence < 0.6, or the question needs medical judgment.
- Used by eligibility assistant (`/ask`), site concierge, and check generation.
- Done when: eligibility eval reports accuracy and escalation precision/recall.

### 9.11 Data-manager agent (`agent/`) (extra)
- Daily (optional) loop: Gemini gets current blockers, aging, top risks, and tools: `list_blockers`, `get_site_summary`, `estimate_impact(action)` (runs an in-memory forecast with the action applied; fork-based for confirm), `draft_action(kind, target)`.
- Output: up to 5 proposed actions with expected ΔP50 and citations → `ops.drafts(kind='agent_action')`. Approved actions are applied (e.g. escalate site, prioritize queries, schedule call).
- Eval: P50 after N days with agent actions approved vs without, on two forks.

### 9.12 Exports
- CSV for queries, findings, reconciliation. Signal review meeting pack (PDF): flagged patients, eDISH image, signed notes. Natural-language eval report: Gemini summary of an eval run with citations to `eval.metrics` rows.

## 10. Gemini layer (`llm/`)

- `LLMClient` ABC: `structured(job, prompt, schema, model) -> LLMResult`, `embed(texts) -> list[list[float]]`. Implementations: `GeminiClient`, `ReplayClient`, `RecordingClient`.
- Call pattern: `client.models.generate_content(model, contents, config=GenerateContentConfig(temperature=0, response_mime_type="application/json", response_schema=<Pydantic model>))`; validate with Pydantic; one retry with the validation error appended. Embeddings: `client.models.embed_content(model, contents, config=EmbedContentConfig(output_dimensionality=EMBED_DIM))`. Verify SDK signatures against current docs.
- Cache key: sha256(job + model + prompt_version + rendered prompt). Log every call to `ai.llm_calls`.
- Concurrency: asyncio semaphore (5). Backoff on 429.
- Jobs and schemas (`schemas.py`): `CheckSpecProposal`, `QueryDraft`, `TermDecision`, `FindingOut{title, severity, claims[{text, citations[{table, pk, column, value, quote}]}]}`, `CausalityOut`, `ReviewNote`, `VisitAgenda`, `FollowUpLetter`, `QAAnswer`, `XwalkDecision`, `SqlProposal`, `AgentPlan`, `EvalSummary`, `Narrative`.
- Prompts in `prompts/*.md` with a version header. Shared rules in every prompt: use only provided evidence; cite table+pk for every claim; copy values exactly; no diagnosis; say "insufficient evidence" when needed; never mention treatment arm.

## 11. Verifier (`verification/`)

Checks per claim: `RowExists` (allow-listed table, row exists), `ValueMatches` (normalized: ISO dates, 2-dp numbers, case-folded trimmed strings), `ClaimNumbersCovered` (every number/date in claim text appears in a cited cell, or a derived ratio within 1%), `QuoteInSource` (exact substring after whitespace normalization), `EvidenceSubset` (citations ⊆ evidence handed to Gemini), `RoleVisible` (citing role can read every cited row).
Status: claim verified if all pass; finding/draft `verified` (all claims), `partial` (≥1 verified, none contradicted), `blocked` otherwise. Blocked items are stored but hidden from review queues. Grounding rate = verified claims / all claims.
Rule-based flags carry `{rule, threshold, comparison_group, value, source_rows}` and render in the same evidence panel.

## 12. Eval harness (`evals/`)

- `ForkManager` ABC; `TigerForkManager` (wrap `tiger service fork` / `tiger service delete`; confirm flags with `--help`; parse JSON output; measure fork seconds); `TemplateDbForkManager` (`CREATE DATABASE "<name>" TEMPLATE golden` / `DROP DATABASE`).
- Injectors (one class each, registry by `kind`): `impossible_value, date_order, unit_mixup, missing_visit, duplicate, missing_field, lab_value_mismatch, lab_unit_mismatch, lab_one_sided, stale_feed, sae_date_shift, sae_synonym (negative control), sae_coded_change, sae_causality_flip, sae_seriousness_flip, sae_missing_outcome, sae_edc_only, sae_safety_only, sae_death_mismatch, hys_law_plant, site_creep, rare_ae_cluster, ae_lab_link, site_personality, xwalk_noise`.
- Blind planting: seed drawn at run time (`secrets.randbelow`), stored in `eval.scenario_runs`; injectors run as `eval_admin`; planted rows recorded in `answer_key.planted` with `scenario_run_id`.
- Run loop: create scenario run → fork → inject → set clock → advance N days on fork → score as `eval_admin` → write `eval.metrics` → delete fork (always, in `finally`).
- Baseline: before scoring, findings that also appear on an un-injected fork run are excluded from false positives.
- Metrics per module: precision, recall, F1 (checks, lab recon, SAE recon, medical signals, sites top-k for rule and model, crosswalk); acceptable-vs-actionable accuracy; synonym false-positive rate; causality agreement + kappa; eligibility accuracy + escalation P/R; forecast backtest absolute error + P10–P90 coverage; agent ΔP50; grounding rate, blocked claims, tokens, latency, fork seconds.
- Scenario YAML:
```yaml
name: full
advance_days: 60
model: ${GEMINI_FAST_MODEL}
prompt_version: v1
injections:
  - {kind: impossible_value, count: 10}
  - {kind: sae_causality_flip, count: 5}
  - {kind: sae_synonym, count: 5}
  - {kind: hys_law_plant, count: 2}
  - {kind: site_personality, count: 1, params: {personality: too_perfect}}
```
- `make eval SCENARIO=full REPEATS=3` prints a metrics table and stores everything.

## 13. API (FastAPI, base `/api`)

Headers: `X-Role` (default `data_manager`), `X-Site-Scope` (optional CSV), `X-User` (audit actor). Each request runs in a transaction with `SET LOCAL ROLE` and `SET LOCAL app.site_scope`. Long jobs return `202 {job_id}`; progress via SSE `GET /jobs/{id}/events`.

- System: `GET /health`, `GET /me`, `GET /jobs/{id}`, `GET /jobs/{id}/events`
- Sim: `GET /sim/clock`, `POST /sim/advance {days}`, `POST /sim/reset {seed}`
- Lock: `GET /lock/readiness`, `GET /lock/forecast`, `GET /lock/forecast/history`, `POST /lock/whatif {hypothetical}`, `POST /lock/backtest {at_day}`
- Checks: `GET /checks`, `GET /checks/{id}`, `POST /checks/generate`, `POST /checks/{id}/approve`, `POST /checks/{id}/reject {reason}`, `POST /checks/{id}/dry-run`, `GET /checks/effectiveness`, `GET /failures`
- Queries: `GET /queries?state&site&min_priority`, `GET /queries/{id}`, `PATCH /queries/{id}`, `POST /queries/{id}/approve`, `POST /queries/{id}/close {reason}`, `POST /queries/{id}/translate {language}`, `GET /queries/aging?by=site`, `GET /digests`, `POST /digests/{id}/approve`
- Recon: `GET /recon/labs`, `GET /recon/sae/pairs`, `GET /recon/sae/unmatched`, `GET /recon/sae/summary`, `GET /recon/sae/cases/{id}/versions`, `POST /recon/sae/cases/{id}/causality`, `GET /causality/{id}`
- Mock safety: `POST /mock-safety/cases`, `GET /mock-safety/cases`, `GET /mock-safety/cases/{id}`
- Medical: `GET /medical/review-list`, `GET /medical/patients/{usubjid}/profile`, `GET /medical/edish`, `GET /medical/trends?test&by`, `GET /medical/clusters`, `POST /medical/patients/{usubjid}/notes`, `POST /drafts/{id}/sign`, `POST /medical/escalations`, `GET /medical/escalations`, `PATCH /medical/escalations/{id}`
- Protocol: `POST /protocol/ask {question}`, `GET /search/protocol?q`
- Sites: `GET /sites`, `GET /sites/{id}`, `GET /sites/{id}/kris?from&to`, `GET /sites/{id}/explain`, `GET /sites/visit-plan?month`, `POST /sites/{id}/agenda`, `POST /sites/{id}/letter`, `GET /sites/{id}/scorecard.pdf`, `GET /issues`, `PATCH /issues/{id}`
- Agent: `POST /agent/plan`, `GET /agent/actions`, `POST /drafts/{id}/approve`, `POST /drafts/{id}/reject`
- Findings/evidence: `GET /findings`, `GET /findings/{id}`, `PATCH /findings/{id}`, `GET /citations/{id}/source`, `GET /lineage/{entity}/{id}`
- Hub: `GET /hub/catalog?q`, `GET /hub/xwalk?entity&status`, `POST /hub/xwalk/{system}/{source_id}/confirm`, `GET /hub/dq`, `GET /hub/questions`, `GET /hub/questions/{n}`, `POST /hub/ask {question}`
- Search: `GET /search/terms?q` (returns BM25 hits, vector hits, fused list, method)
- Evals: `GET /eval/scenarios`, `POST /eval/runs`, `GET /eval/runs`, `GET /eval/runs/{id}`, `GET /eval/compare?ids`, `POST /eval/runs/{id}/summary`
- Audit/exports: `GET /audit`, `GET /export/{queries|findings|recon}.csv`, `GET /export/signal-pack.pdf`
- Unblinded (role-gated): `POST /unblind {reason}` (sets session flag, audit-logged), `GET /unblinded/edish`

## 14. Frontend (Next.js)

Global header: trial clock + "Advance 1 / 7 / 30 days", role switcher (sets `X-Role`), site-scope picker, blinded/unblinded banner (red when unblinded), job progress toast. Every database-derived number or claim is clickable to its evidence (citation chip → side panel with source row, cited cell highlighted, verification checks).

| Route | Content |
|---|---|
| `/` | Lock readiness: P50 date + P10–P90 band, checklist, top blockers with ΔP50, forecast history chart, vs 36-day benchmark, What-if dialog, backtest result |
| `/queries` | Priority-ranked worklist, approve/edit drafts, translate, aging heatmap by site, reopened highlight, digests tab |
| `/checks` | Library + generated checks (protocol quote, dry-run count, approve/reject), effectiveness table |
| `/recon/labs` | Lab mismatches, stale feeds |
| `/recon/sae` | Side-by-side pairs with acceptable/actionable/critical badges, unmatched lanes, version history, causality assessment panel, progress to zero, mock-safety inbox tab |
| `/medical` | Ranked review list (blinded) |
| `/medical/patients/[id]` | Swimlane profile (dosing, visits, AEs by grade, conmeds, lab lines with ULN multiples), AE–lab link annotations, note editor + sign, escalate |
| `/medical/liver` | eDISH log–log scatter, thresholds 3 and 2, colored by site or flag (arm only when unblinded) |
| `/medical/trends` | Lab trends by site/visit, rare-AE clusters |
| `/sites` | Ranked sites: rule score, model score, KRI RAG grid |
| `/sites/[id]` | Explained flags, digit histogram, variance, AE rate, KRI history, issues, scorecard PDF |
| `/sites/visit-plan` | Proposed visits/calls with agenda and letter drafts awaiting approval |
| `/agent` | Proposed actions with expected ΔP50, approve/reject |
| `/ask` | Protocol Q&A with quotes or Escalate |
| `/hub` | Catalog search, crosswalk review, DQ dashboard + freshness bars, 5 questions, NL ask (shows SQL + lineage), role demo |
| `/search` | Term search showing BM25 vs vector vs fused |
| `/evals` | Run scenario, per-module metrics, trends, compare runs, backtest, NL summary |
| `/audit` | Filterable audit log |
| `/about` | Data sources + licenses, what is synthetic, architecture |

UI wording rules from §2 apply everywhere. Severity colors: critical red, high orange, medium amber, low gray. Verification badges: verified green, partial amber, blocked red.

## 15. Makefile and clean-clone contract

```
make setup        # uv sync (backend), npm ci (frontend)
make db           # local: docker compose up -d db ; tiger: no-op (uses DATABASE_URL)
make migrate      # apply migrations + roles
make seed         # download → build_golden → scale_sites → build_mock_systems → plant_baseline → build_protocol → seed_search → train_risk_model
make demo         # reset sim to SIM_START_DAY, start api :8000 and web :3000
make eval SCENARIO=full REPEATS=1
make test
make reset        # restore golden state (truncate ops/ai runtime tables, reset clock)
make record-llm   # LLM_MODE=record over seed + one 60-day demo run to refresh fixtures
```

`README.md`: what it is, sheets covered, quick start (the commands above), data sources + licenses, synthetic data summary, architecture diagram, eval instructions, known limits. `DATA.md`: every source, transformation, planted problem type, answer-key location. Commit `fixtures/llm_cache` so `LLM_MODE=replay` runs without a key.

## 16. Tests (pytest, fast)

- Check factory rejects unknown tables/columns; each library check flags a fixture error and passes a clean row.
- Query state machine: every legal transition; illegal transitions raise.
- SAE classifier: each rule row in §9.5 table.
- Hy's Law boundary: 3.0×/2.0× flagged, 2.9× not.
- Verifier: wrong value blocked, invented number blocked, fabricated quote blocked, correct claim passes, out-of-role citation blocked.
- Monte Carlo: deterministic with seed; more open items → later P50.
- Crosswalk normalizer cases.
- NL SQL guard: rejects DDL/DML, multiple statements, `unblinded`/`answer_key` references.
- Role test: `medical_monitor` cannot select from `unblinded.randomization`; `study_lead` cannot select `edc.ae`.

## 17. Milestones (build order)

1. **Skeleton** — repo, Makefile, Docker, FastAPI health, Next.js shell with header/role switcher, migrations 001–009 applied. *Done when* `make setup migrate demo` works on a clean clone.
2. **Golden data** — download, normalize, scale to 24 sites, mock systems, baseline planting, protocol, search seed. *Done when* row counts per table print and DATA.md drafted.
3. **Clock + checks + queries** — daily cycle, 26 checks, query lifecycle, site responder, aging. *Done when* advancing 30 days shows opens/closes/reopens.
4. **Verifier + Gemini layer + evidence UI** — client, replay cache, finding schema, verifier, citation side panel.
5. **SAE recon** — matcher, hybrid terms, classifier, query drafts, recon page.
6. **Medical** — CTCAE, Hy's Law, eDISH, review list, profiles (blinded).
7. **Sites** — KRIs, anomaly tests, rule score, site pages.
8. **Eval harness** — fork manager, injectors, scorer, evals page. *Checkpoint: complete demoable product.*
9. **Lock forecast** — readiness, KM + Monte Carlo, blockers, history.
10. **Lab recon + generated checks + digest + effectiveness.**
11. **Hub** — crosswalk, catalog, lineage, DQ, 5 questions, roles/RLS demo.
12. **Medical Best** — trends, clusters, AE–lab links, notes, escalations, eligibility assistant.
13. **Sites Best** — risk model training + comparison, visit planner, agenda/letters, issues, scorecard PDF.
14. **SAE Best + causality** — causality assessor + eval, E2B mapper, mock safety API, follow-up continuous recon.
15. **Forks extras** — what-if, backtest.
16. **Agent + NL ask + translation + signal pack + NL eval report.**
17. **Hardening** — `make record-llm`, clean-clone test on a fresh machine, README/DATA.md final, tests green.

## 18. Unverified items — check before relying on them

- Exact Tiger CLI syntax and JSON output for forking/deleting services (`tiger service fork --help`), fork time, free-tier service/fork limits.
- Whether `pg_textsearch` and `vectorscale` are enabled on the Tiger service and in the local Docker image. Fallbacks: Postgres `tsvector` + `ts_rank_cd` for keyword search; `pgvector` HNSW index for vectors. Keep both behind `search/hybrid.py`.
- pg_textsearch syntax: `CREATE INDEX ... USING bm25 (col) WITH (text_config='english')`; rank with `ORDER BY col <@> to_bm25query('q', 'index_name')` (scores are negative; lower is better).
- Which SDTM domains and columns exist in the pilot files (RFICDTC, SV, TV, DS, CM, MH); how many serious AEs and liver abnormalities exist. Adapt generators accordingly.
- Current Gemini model IDs, `gemini-embedding-2` output dimensionality support, and google-genai SDK signatures.
- CTCAE thresholds for the encoded labs against the current NCI file.
