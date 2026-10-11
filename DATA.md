# DATA.md

All data is public or synthetic. Nothing here is real patient data.

## Sources
| Source | Use | License / note |
|---|---|---|
| CDISC SDTM/ADaM pilot (`cdisc-org/sdtm-adam-pilot-project`, study CDISCPILOT01) | EDC base: DM, AE, LB, VS, SV, EX, CM, MH, DS, TV | Educational use (CDISC pilot) |
| ClinicalTrials.gov API v2, NCT00505167 | Eligibility criteria quoted verbatim in `data/protocol/protocol.md` | Public record. Its locations are real hospitals and are **not** used (fictional sites only) |
| openFDA `drug/event` | Structure reference for the mock safety payload (`data/raw/openfda_sample.json`) | Public domain |
| CTCAE v5.0 | Hand-encoded thresholds in `app/medical/ctcae.py` | **Not yet confirmed** against the current NCI file |

## Pipeline (`make seed`, deterministic for a given `SEED`)
1. `download_data` - fetch sources to `data/raw/` (gitignored).
2. `build_golden` - normalize to `edc_pending.*`: ISO dates, partial dates imputed to day 1 / Jan (`date_imputed`), undated rows excluded and logged, null-valued labs/vitals dropped, `site_id` denormalized, `x_uln` and CTCAE grade computed, bilirubin converted to mg/dL. `RFICDTC` is blank in the pilot, so consent = first visit minus U(0,14) days. Each subject's timeline is shifted so consent falls in the first ~180 days after 2026-01-05.
3. `scale_sites` - 17 pilot sites -> 24 (7 synthetic sites `901-907`, 14 cloned subjects each, ~3% value noise, `is_synthetic=true`). Personalities (2 sites each: under_reporter, sloppy_entry, too_perfect, rule_bender, slow_responder; 14 normal) go **only** to `answer_key.site_personality`. Entry lags set `entered_at`; a child row never enters before its subject.
4. `build_mock_systems` - `lab_vendor.transfer` (aliased `PT701-1015`, DD/MM/YYYY, spelled-out tests, bilirubin in umol/L), `safety.case_versions` (E2B-shaped, ~20% get a v2), `ctms.*` (name variants, one duplicate site, one site with no EDC subjects), `irt.kits`, `unblinded.randomization` (only place the arm exists). Severe AEs are promoted to serious (`augmented=true`) because the pilot has only 4 serious AEs. Causality reference labels (simplified WHO-UMC) go to `answer_key.causality_reference`.
5. `plant_baseline` - 238 recorded plants in `answer_key.planted`: 149 edit-check errors, 25 lab mismatches + 1 stale feed, 30 SAE discrepancies, 3 Hy's-Law-pattern subjects, 1 ALT-creep site, 1 rare-AE cluster (4 cases), 6 AE-lab co-occurrences, 19 hub-quality problems.
6. `finalize_golden` - sets `ops.sim_clock` (study start 2026-01-05, today = start + `SIM_START_DAY`) and releases staged rows with `entered_at <= today`. The rest stays in `edc_pending.*` for the daily cycle.
7. `build_protocol` - `protocol.md` (real eligibility + synthetic summary, sections tagged), 40 eligibility Q&As (every quote verified as an exact substring), chunks to `ai.protocol_chunks`.
8. `seed_search` - `ai.ae_terms` (coded, verbatim and synonym terms) and `hub.catalog`.

## Synthetic elements
Site names/cities, 7 cloned sites, subject date shifts, personalities and every planted problem, the whole mock external systems, the protocol summary (everything marked `[SYNTHETIC]`), eligibility questions, deviations, monitoring visits, screening rows.

## Answer key
Everything the detectors must not see lives in schema `answer_key` (readable only by `eval_admin`): `site_personality`, `planted`, `causality_reference`, `crosswalk_truth`, `eligibility_qa`.
