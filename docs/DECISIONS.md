# Decisions (deviations from LOCKSTEP_BUILD_SPEC.md)

- **DB host port 5433**, not 5432: a Homebrew Postgres already binds localhost:5432 on the dev machine.
- **app_admin created by `docker/init.sql`**: the timescaledb-ha image ignores `POSTGRES_USER`.
- **Verified §18 (local image):** `timescale/timescaledb-ha:pg17` ships `timescaledb`, `vectorscale` and `pg_textsearch`; migrations 001–009 apply cleanly. No fallback to tsvector/pgvector needed locally.
- **Tiger CLI not installed**; `FORK_BACKEND=template` is the default until it is.
- `hub.catalog` BM25 index is named `catalog_bm25` (the spec left it unnamed).
- Migration 009 grants roles to the connecting user so `SET LOCAL ROLE` works, and creates `eval_admin` with a local-dev password.

## Milestone 2
- **Timeline compressed**: pilot dates span ~2 years; each subject is re-based so consent lands in the first ~180 days from 2026-01-05, so a trial can reach lock within about a year of sim time.
- **Blinded dose**: `EXDOSE` in the pilot reveals the arm (placebo = 0), so `edc.exposure.dose` is a constant 1.0.
- **Bilirubin stored in mg/dL** in the EDC (pilot is umol/L); the vendor feed sends umol/L, matching the spec's /17.1 conversion.
- **Digit-preference baseline**: the pilot's real sites show strong terminal-digit preference in BP (up to ~60% ending in 0). Integer noise (-4..+4) is added to BP/pulse before cloning so the anomaly test has a clean baseline; planted `too_perfect` sites then stand out.
- **Vitals timestamps**: rows within one visit get +2 min per timepoint so (subject, test, time) is unique and the duplicate check has no false alarms.
- **Serious AEs**: only 4 in the pilot; all 44 severe AEs promoted (48 cases, `augmented=true`), leaving 18 clean cases after 30 planted ones.
- **Migration 010 (additive)**: `edc_pending.subject_updates` (disposition/death appear only when they occur) and `hub.lab_test_map`.
- **Not used**: ClinicalTrials.gov locations (real hospitals). No NEUT test exists in the pilot, so AE-lab links use platelets/hemoglobin.
- **Gemini deferred**: no API key, so embeddings are NULL (search falls back to BM25) and safety narratives are deterministic templates. Run `make record-llm` with a key to backfill (milestone 4/17).
- **CTCAE thresholds** are unverified against the current NCI file (spec §18).
- `train_risk_model.py` joins the seed chain in milestone 13.

## Milestone 3
- **Auto-approve for the simulator**: humans approve every query (rule 2), but a 30-day `advance` would stall without a human. `POST /sim/advance` takes `auto_approve` (default true): a simulated data manager (`actor = sim:auto`, audit-logged) approves drafts and accepts site explanations. With `auto_approve=false` queries stay Draft until a person approves them (tested).
- **Active checks: 22 of 26.** chk_22 (serious AE without safety case) waits for SAE reconciliation (M5); chk_24-26 (central-lab vs EDC) wait for lab reconciliation (M10). They are registered with `active=false`.
- **Telephone contacts are scheduled visits** (protocol §5), so the missing-visit, window and visit-order checks include Weeks 10/14/18/22. `AMBUL ECG` and `RETRIEVAL` visits are not in the protocol and are ignored.
- **Data-driven required fields** (chk_16): a unit/range is required only for tests where >= 90% of rows already have it, so unitless tests (pH, specific gravity) are exempt.
- **Weight lb/kg check** compares a reading with the median of the same subject's *other* readings (works with 2 readings).
- **Site simulator lives apart from detectors**: `app/sim/world.py` reads `answer_key.site_personality` through the eval_admin connection; nothing in checks/queries imports it. Corrections are heuristics over visible data (subject median, expected visit date), never the planted truth.
- **Determinism**: response RNG is keyed by (seed, day, check, source row, reopen count), not by random query UUIDs; `reset` restarts runtime identities. Same seed -> identical run (tested).
- **Golden snapshot** (`golden` schema, migration 011) is written by `finalize_golden`; `make reset` / `POST /sim/reset` restores from it in about a second.
- **Query volume**: every failure becomes a query; the weekly minor-issue digest (priority < 0.15) arrives in M10. One query per source row: when several checks fail on one row, the most severe wins.
- **Continuous aggregates** are refreshed once at the end of an `advance` job, not after every simulated day.
- Query text is a template; Gemini drafting arrives in M4.

### Check-library results (`python -m scripts.score_checks`, sim run to the end of the data)
Planted edit-check errors detected: **145 / 149 (97%)**. Misses: 2 missing `AMBUL ECG REMOVAL` visits (not protocol-defined) and 2 lb/kg errors on subjects with a single weight reading (nothing to compare against).
Failures on unplanted rows: 756 of 918. These are mostly genuine behavior of the pilot data (visits outside the +/-7 day window: 304, skipped scheduled visits: 342, AEs dated before the derived consent: 40, ALT/AST >= 3x ULN without a hepatic AE: 25), so the true false-alarm rate cannot be separated from natural findings without a ground truth for them.
