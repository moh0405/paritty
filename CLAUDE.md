# LockStep - guide for Claude Code sessions

Continuous clean-to-lock copilot for clinical trials (HackRU 2026). The full design is in `LOCKSTEP_BUILD_SPEC.md`; read §2 (rules) and §17 (milestones) first. Deviations from the spec and their reasons are logged in `docs/DECISIONS.md`; data sources and the pipeline are in `DATA.md`.

## Non-negotiable rules (spec §2)
1. Public or synthetic data only. Never add real patient or site data.
2. **Humans approve** every generated check, query, correction, note, letter, agenda, eligibility answer and agent action. Auto-approval exists only for the simulator (`sim:auto`, audit-logged).
3. **Blinding**: the treatment arm lives only in `unblinded.randomization`. Never put arm data in prompts, evidence, charts or blinded API responses.
4. Neutral wording in all user-facing text: "potential", "needs review", "reason to look". Never "fraud", "misconduct" or "diagnosis".
5. Detection is deterministic. Gemini drafts and adjudicates; every Gemini claim must carry citations and pass `app/verification` or it is blocked. Gemini never produces executable logic.
6. App and detector code must **never read the `answer_key` schema**. Only the eval scorer and the simulator's `WorldModel` (via `eval_admin`) may.
7. Every state change writes to `audit.log`.

## Run it
```
cp .env.example .env            # add your own GEMINI_API_KEY (never commit it)
make setup db migrate seed      # docker TimescaleDB on :5433, deterministic data
make demo                       # API :8000, web :3000
make test                       # backend pytest (DB tests skip if the DB is unseeded)
cd frontend && npx tsc --noEmit && npm run lint
```
`make reset` restores the seeded state (day 60). `make golden` rebuilds the eval template database. `make eval SCENARIO=smoke` runs an eval on a database fork.

## Working conventions
- **LLM modes**: default `LLM_MODE=replay` (recorded responses in `backend/fixtures/llm_cache`, template fallback on a miss). The Gemini free tier is rate-limited, so tests and dev runs must use `LLM_MODE=replay LLM_QUERY_DRAFTS=0`. Do not record fixtures unless asked.
- **Your own database**: do not run resets, long simulations or the full suite against a database someone else is using. Create your own (`CREATE DATABASE mydev TEMPLATE lockstep_golden`) and point `DATABASE_URL` / `EVAL_ADMIN_URL` at it.
- **Migrations are additive** and numbered. Ranges: 001-099 main line, 100-199 and 200-299 for the two parallel contributors (see CONTRIBUTING.md). Never edit a migration that has been merged.
- **Tests**: pure-logic tests first (no DB), DB tests use the rolled-back `db` fixture. Add a test for every rule or classification you add. Keep the suite green before opening a PR.
- **Retry discipline**: if the same failure survives three different fix attempts, stop, record it under "Known issues" in `docs/DECISIONS.md`, and move on. No unbounded loops or polling.
- Record every deviation from the spec in `docs/DECISIONS.md` under a milestone heading (append only; resolve merge conflicts there by keeping both sides).
- Prefer deterministic over LLM, simple over clever, end-to-end over complete.

## Layout
`backend/app/` (api, checks, queries, sim, recon, medical, sites, forecast, evals, llm, verification, search, db) - `backend/scripts/` (seed pipeline, scorers) - `backend/tests/` - `frontend/` (Next.js App Router) - `data/protocol/` (synthetic protocol and Q&A).
