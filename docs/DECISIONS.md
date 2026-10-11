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

## Milestone 4
- **Embeddings**: `gemini-embedding-2` folds a list of inputs into ONE vector, so the helper embeds one text per call (5 threads) and waits out 429s (free tier: 100 requests/min). Vectors are cached in `fixtures/llm_cache/embeddings`.
- **Free-tier speed**: a live drafted query takes ~15 s including rate-limit waits (11 drafts took 2.7 min). Default mode stays `replay`; a cache miss returns a labeled stub and the drafter falls back to the template. Only the first 3 sim days are recorded so far; `make record-llm` records the 60-day demo (expect tens of minutes on the free tier).
- **Only fully verified drafts are sent.** A draft's claims are verified, and the query text itself is checked as one more claim whose citations are the union of the others, so a number or date in the text that no cited cell backs is caught. `partial`/`blocked` drafts are stored (hidden from review queues by default) and the deterministic template is used instead; the template carries its own verified claims, so every query has an evidence panel.
- **Verifier rules**: numbers and dates in a claim must appear in a cited cell, or be carried by the rule itself (thresholds and the system-computed expected date), or be a ratio of two cited numbers within 1%. Identifiers (01-701-1015, PT701-1015) are ignored when extracting numbers. A NULL cell may be cited as null/none/n/a/missing.
- **RoleVisible runs on the caller's connection** inside a rolled-back savepoint (`SET LOCAL ROLE`), not on a pooled connection: a second connection cannot see rows the simulation has inserted but not committed and blocks on locks the simulation holds (this hung the test suite once).
- **LLM calls are logged to `ai.llm_calls` on the caller's connection** for the same reason; without a connection nothing is logged.
- **Prompt/arm safety**: evidence rows come from tables that never contain the treatment arm; a test asserts the prompt has no arm terms.
- UI wording stays "reason to look" (confirm) / "dismiss"; the evidence panel was typechecked and linted but not viewed in a browser (the Chrome extension was not connected).

### Live result (11 Gemini drafts, first 3 sim days)
First pass: 9 verified, 1 partial, 1 blocked. All three failures were verifier gaps, not model errors: a genuinely NULL severity cited as `null`, and a date the rule itself had computed. After fixing both (with tests), replaying the same cache gives 11/11 verified, 31/31 claims verified (grounding rate 100%). Small sample: it shows the pipeline works, not a measured error rate for the model.

## Milestone 5
- **SAE discrepancies reuse the check pipeline.** Matching and classification are Python (Hungarian assignment, term similarity), so they cannot be compiled to SQL. `SaeReconciler` computes the full picture every simulated day and writes the actionable/critical items into `ops.check_failures` under dedicated specs (`sae_onset`, `sae_term`, `sae_seriousness`, `sae_causality`, `sae_outcome`, `sae_death`, `sae_safety_only`, `sae_fatal_one_sided`, plus `chk_22` for EDC-only). `CheckRunner` skips them. Queries, evidence, approvals, responses and auto-close then work unchanged, and a failure resolves when the discrepancy disappears. Acceptable differences are shown on the recon page but raise no query.
- **Recon history and a flattened case view** (migration 012): `safety.v_cases` (one row per case version, dates as real dates, free text kept separate) is what claims cite and what the matcher compares; `ops.sae_recon_history` stores daily counts for the progress-to-zero chart.
- **Term similarity** is: exact -> dictionary/synonym (both map to the same coded term, 0.95) -> cached decision -> embedding cosine (>= 0.8 same, < 0.5 different) -> Gemini adjudication for the 0.5-0.8 grey zone, stored once per pair in `ai.term_decisions`. Embedding similarity alone is a weak signal here ("heart attack" vs "myocardial infarction" scores 0.79, unrelated "nausea" vs "syncope" scores about 0.6), so the dictionary and the adjudicator carry the decisions. Hybrid BM25 + vector search (RRF) powers the term-search page.
- **pg_textsearch needs the schema-qualified index name** (`to_bm25query('q', 'ai.ae_terms_bm25')`); an unqualified name fails. A tsvector fallback is in place behind `search/hybrid.py`.
- **Safety follows EDC in the simulation.** When a site confirms its EDC value, the simulated safety desk issues a follow-up case version that agrees with it (or opens the missing case); for a safety-only case the site enters the missing AE in EDC. This is a simplification of "which side is right" and is what lets discrepancies resolve and the progress-to-zero line fall. Follow-ups take effect the same day so the answer is judged after the reconciliation runs.
- **EDC-only grace period**: a serious AE is not flagged as missing from the safety database until 3 days after it was entered (protocol: 24-hour reporting).
- **Subject identifiers** in the safety feed are parsed deterministically (`recon/refs.py`) until the hub crosswalk (milestone 11) replaces it.
- **Causality assessment, E2B message mapping and the mock safety API** are milestone 14. A causality conflict is classified actionable and flagged `needs_causality`.
- **Bug found and fixed:** `reset` restored the EDC but not `safety.case_versions`, so follow-up versions created by the simulator leaked into later "clean" runs. The golden snapshot now includes the safety cases.
- **Robustness:** every Gemini request has a 60 s timeout; a failed or timed-out adjudication leaves the pair undecided instead of stopping the simulation. `LLM_QUERY_DRAFTS=0` skips query drafting so only term decisions are recorded.
- Query text for SAE items uses its own template and never exposes the internal case row reference.

### SAE reconciliation result (`python -m scripts.score_sae_recon`, sim run to the end of the data, replay mode)
- Planted actionable discrepancies detected: **22 / 22 (100%)**; precision **22 / 25 (88%)**. Three flags landed on subjects with no planted item (`01-703-1119` onset and term, `01-716-1103` outcome): natural differences or unpaired follow-ups, not investigated.
- Acceptable differences handled correctly (not flagged): **7 / 8**. The miss is one of the 5 planted synonyms (synonym false-positive rate 20%): that pair fell in the embedding grey zone and no adjudication was cached, because the Gemini free-tier quota was exhausted during recording (only 11 term decisions are cached). Re-running with quota (`LLM_MODE=record LLM_QUERY_DRAFTS=0`) should record the rest.
- Open discrepancies at the end of the run: 3 (items the simulated sites did not fix).

## Milestone 6
- **Review list is computed on demand**; each item also gets a *rule-based finding* (once, keyed by signal) whose claims are formatted from the cited cells and pass through the same verifier, so rule flags and AI drafts share one evidence panel. Findings carry `{rule, threshold, comparison_group, value}` in their detail.
- Hy's Law = ALT or AST >= 3x ULN and bilirubin >= 2x ULN with the two results within 30 days (most extreme qualifying pair); ALP is context only. Wording is always "potential ... requires medical review".
- Rare-AE test: Poisson against the rate seen at the *other* sites, smoothed by +0.5 events, so a term seen nowhere else is not treated as rate 0 and the "study rate < 1%" condition still works while enrolment is small.
- **Blinding**: profile, eDISH and review list contain no arm (tested). The arm is available only through `/api/unblinded/edish`, which needs the `unblinded_statistician` role *and* a prior logged `POST /api/unblind` with a reason; every view is audit-logged. Audit/state writes for that gate use the system connection, because the role deliberately has no write grants.
- The IRT reference is matched to an EDC subject by a deterministic rule (`recon/refs.py`) until the crosswalk (milestone 11) replaces it.

## Milestone 7 (site risk)
- Eight KRIs with the spec's bands; `na` is returned when a comparison is meaningless (zero median, or under 3 patient-months of exposure). KRIs, anomaly tests and scores are computed on the first day and then every Monday of simulated time (a daily run of the six anomaly tests made a 330-day run noticeably slower).
- Six anomaly tests: terminal digit (chi-square), pulse variance ratio, duplicated vital-sign sets, AE under-reporting (lower-tail Poisson against the other sites' rate), visit timing (KS) and borderline eligibility values (binomial). The pilot data's own digit preference was removed in M2 so the digit test has a clean baseline.
- **Rule score** = mean of capped (+/-4) robust z-scores over the KRIs and anomaly features, mapped linearly to 0-100, so a typical site sits near 50. AE and SAE rate are scored two-sided (unusually low or high). The plain-English explanation states the data, comparison group, threshold and value.
- Result (sim run to the end of the data, `python -m scripts.score_sites`): the rule score puts **7 of the 10 planted problem sites in the top 10, 8 of 10 in the top 12 and all 10 in the top 15**. The learned model score is milestone 13. Wording avoids any accusation: scores are "reasons to look".

## Milestone 8 (eval harness)
- **Forks**: `CREATE DATABASE ... TEMPLATE lockstep_golden` (about 0.2 s here, extensions and hypertables intact). The golden template is built by `make golden` (also the last step of `make seed`); building it terminates other sessions on the main database. `TigerForkManager` is implemented but unverified: the Tiger CLI is not installed, so its flags and JSON output are guesses.
- **Each run uses two forks**: a control fork (same days, no injections) and an injected fork. Findings that also appear in the control are excluded from false positives; recall counts only items planted by this run (baseline plants are in both and cancel out).
- Evals run in their own process (`python -m app.evals.run`, spawned by `POST /api/eval/runs`) because switching databases is process-wide; metrics are written to the main database, and the planted rows are copied to the main `answer_key.planted` with the run id.
- Injectors change data on the app connection and write the answer key on the `eval_admin` connection; the seed is drawn with `secrets.randbelow` at run time. 24 of the spec's 25 kinds exist; `xwalk_noise` comes with the crosswalk (milestone 11). Injected rows are chosen among staged rows that enter EDC during the run, so they are detectable.
- First smoke run (25 days): edit-check recall 1.00 / precision 0.75, SAE reconciliation 1.00 / 1.00, Hy's Law 1.00; the fork took 0.15 s.

## Milestone 9 (lock forecast)
- **Model**: remaining work items are open queries (conditional on how long they have been open), queries expected from each ongoing subject's last two visits (site query rate x visits), each ongoing subject's last visit plus the site's entry lag, and projected enrolment (planned 400, recent enrolment rate with a lognormal uncertainty). Resolution times are drawn from per-site Kaplan-Meier curves, shrunk toward the pooled curve with fewer than 10 closed queries. Lock = latest completion + 5 days. 2000 simulations, vectorized; about 0.2 s per simulated day, so a forecast is stored every day.
- **Blockers** are leave-one-site-out and leave-one-category-out changes in P50 on the same random draws. Categories are the CTQ classes plus `sae_recon`, `lab_recon`, `expected`, `visits`, `enrollment`.
- **No peeking**: the forecast never reads staged (future) rows; enrolment is projected from the recent rate. Early forecasts are therefore too late while sites are still being activated (day 1 said May 2027; by day 120 it said January 2027, which is where the simulated data end).
- Readiness has 7 criteria; lab reconciliation, signed notes and generated checks count as met until milestones 10 and 12 create the work, and then they matter.
- Hypothetical (what-if) support is built in: per-site response mean override and "treat these categories as already done".

## Milestone 10 (lab reconciliation, generated checks, digest, effectiveness)
- **Lab reconciliation** matches central-lab records to EDC results per subject on test and collection date (+/-1 day, exact dates first, one-to-one), converts bilirubin from umol/L before comparing, tolerates 1% relative difference, and reports unit differences separately from value differences. Specs `chk_24` (value), `chk_25` (one side only), `chk_26` (unit) and `lab_stale_feed` are detected in Python and written to `ops.check_failures` for the subjects touched that day (files received or EDC lab rows changed), so a daily run stays cheap. The stale-feed item has no site and is not turned into a query.
- **Grace rules** avoid noise: an EDC result is "missing from the central lab" only after the file feed has reached its collection date plus 5 days (so a late feed does not raise a wave of false alarms); a central-lab result is "missing from EDC" only after 30 days (sites enter results up to 25 days late).
- **Simulator**: the central lab corrects its records or sends missing ones, and a site enters a result only the lab holds, when a query is answered correctly (`sim/lab_desk.py`).
- Result (baseline-planted differences, `python -m scripts.score_lab_recon`): **23 of 26 (88%)**: value 10/10, unit 5/5, stale feed 1/1, one-sided 7/10. The 3 misses are planted one-sided items collected near the end of the simulated data, still inside the 30-day vendor-only window. Spec target was 90%.
- **Bug found and fixed**: `reset` restored file dates but not the contents of the lab feed, so corrections from one run leaked into the next (recall fell to 31%). The feed is now snapshotted in `golden.lab_transfer` by migration 013 (taken at migration time, before any simulation) and restored on reset.
- **Generated checks**: Gemini proposes (`check_generation` prompt, parameters returned as a JSON string); a deterministic extractor covers the protocol's numeric eligibility limits (age, screening SBP, ALT, bilirubin) so the feature works with no LLM. Every proposal is validated (type allow-list, exact quote in the cited chunk, compiles over the column allow-list), dry-run against current data, and stored as `pending_approval`; rejected proposals are returned with a reason but never stored. Only a data manager can approve or reject. A newly approved check is evaluated over existing data once, then incrementally.
- **Digest**: queries with priority below 0.15 wait; on Mondays they are grouped per site into one digest draft. Approving a digest approves its queries (in auto mode the simulated data manager approves it). Over 60 days: 9 digests covering 13 minor queries.
- **Effectiveness**: in-app view counts queries closed by correction (confirmed) versus closed with the site's explanation (dismissed) and flags checks with 5+ decisions and a dismissed share above 50% for retirement; `eval_scores` compares with the planted truth (eval only).
