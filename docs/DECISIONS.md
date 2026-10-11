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
