# Work split (two contributors, two Claude sessions)

Updated after Milestone 11. `main` has Milestones 1-11. Push when a milestone is done and its tests are green; open PRs from branches, never commit to `main` directly (see CONTRIBUTING.md).

| Owner | Work | Branch | Migration range |
|---|---|---|---|
| **Contributor A** (moh0405's Claude) | M12 medical best, M14 SAE best + causality, M15 forecast what-if/backtest, M16 agent + NL ask + translation + PDF pack, M17 hardening | `feat/m12-...`, `feat/m14-...` ... | 013-099 (main line) |
| **Contributor B** (rudraasakariya's Claude) | Tiger Cloud (`docs/HANDOFF_TIGER.md`), **M13 sites best** (below), browser QA of every page | `feat/tiger-cloud`, `feat/m13-sites-best`, `qa/...` | 100-199 |

## Why this split
M13 lives in `backend/app/sites/`, `backend/app/api/routers/sites.py` and `frontend/app/sites/`: almost no overlap with M12/M14-M16. Tiger work lives in `evals/fork_manager.py`, `docs/` and environment setup.

## M13 brief for Contributor B (spec §9.7 and §14, rows "Sites Best")
Already built (read first): `sites/kris.py` (8 KRIs), `sites/anomaly.py` (6 tests), `sites/risk.py` (`feature_table`, `rule_scores`, `explain`, `store` -> `ops.site_risk`; `model_score` is NULL today), `scripts/score_sites.py` (top-k check), `/api/sites*` and `/sites` pages. Tables `ops.site_risk`, `ops.issues`, `ops.drafts` exist.

1. **Risk model** (`scripts/train_risk_model.py`, `sites/risk_model.py`): simulate ~600 synthetic site histories with random personalities (reuse the section 7.2 generators/personalities in `app/sim/personalities.py`; no database needed), compute the **same features** as `risk.feature_table`, train `HistGradientBoostingClassifier` (problem vs normal, plus multiclass personality), save to `backend/models/site_risk.joblib` (gitignored; the script is part of `make seed`). Explain with permutation importance and per-site top contributing features. Fill `ops.site_risk.model_score` in `risk.store`. Compare against the rule score (precision@k / recall@k) in `scripts/score_sites.py` and in the eval scorer (`evals/scorer.py`, module `sites`). Never read `answer_key` from app code: training uses simulated data only.
2. **Visit planner** (`sites/visit_planner.py`): rank sites by risk x enrolled; action = visit (red), call (amber), remote (green with open issues). `GET /api/sites/visit-plan?month` (register it **before** `/{site_id}` in `routers/sites.py`).
3. **Agenda and follow-up letter drafts** (`sites/letters.py`): Gemini drafts with citations (see `llm/prompts/*.md`, `verification/builders.py`, `queries/drafter.py` for the pattern: draft -> verify -> template fallback). Store in `ops.drafts` (`kind` = `agenda`/`letter`, state `draft`); a human approves (`POST /api/drafts/{id}/approve|reject`, which Contributor A adds in the next push - until then call `ops.drafts` directly in tests). Each approved item opens a row in `ops.issues`.
4. **Issue tracking**: `GET /api/issues`, `PATCH /api/issues/{id}`.
5. **Scorecard PDF**: `GET /api/sites/{id}/scorecard.pdf` (reportlab, one page).
6. **UI**: `/sites/visit-plan` (proposed visits/calls with agenda and letter drafts awaiting approval), issues on `/sites/[id]`, the scorecard link, model score column already present on `/sites`.
Wording: "reason to look", never accusations. Tests: pure-logic first; model reproducible with a seed.

## Interfaces Contributor A will provide (and when)
- `POST /api/drafts/{id}/approve|reject` and `GET /api/drafts?kind=` (first thing in M12).
- Nothing else in M13 depends on M12-M16.

## Hot files (touch in small hunks, rebase often)
`backend/app/main.py` (one router line each), `backend/app/sim/daily_cycle.py`, `frontend/components/Header.tsx`, `frontend/lib/api.ts`, `docs/DECISIONS.md` (append under your own heading).
