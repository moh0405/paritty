# Handoff: Tiger Cloud / Tiger Data side

Owner: @rudraasakariya (and their Claude). Branch: `feat/tiger-cloud`. Migration range for your work: **100-199**.

## Why you
Everything so far runs on a local Docker TimescaleDB image (`timescale/timescaledb-ha:pg17`, port 5433). The spec (§3, §12, §18) targets Tiger Cloud, but the Tiger CLI was never installed on the original machine, so these parts are **unverified guesses**. You have the CLI and Tiger experience, so you own making them real.

## What exists today
- `backend/app/evals/fork_manager.py`: `ForkManager` interface, `TemplateDbForkManager` (works: `CREATE DATABASE ... TEMPLATE lockstep_golden`, about 0.2 s) and `TigerForkManager` (**unverified**: the `tiger service fork` flags and JSON keys are guesses). Selected by `FORK_BACKEND=tiger|template`.
- `backend/app/db/target.py`: switches the whole process to another database URL (used by the eval harness, which runs in its own process).
- `backend/app/db/migrations/001-0xx_*.sql`: extensions (`timescaledb`, `vectorscale`, `pg_textsearch`), hypertables, continuous aggregates, roles, RLS.
- `backend/app/search/hybrid.py`: BM25 + vector search with a tsvector fallback if BM25 is unavailable.
- `.env.example` has `DATABASE_URL`, `EVAL_ADMIN_URL`, `GOLDEN_SERVICE_ID`, `FORK_BACKEND`. `make db` is meant to be a no-op on Tiger.

## Tasks
1. **Verify the CLI contract.** Run `tiger service fork --help` and `tiger service delete --help`; fix `TigerForkManager` to the real flags and output format (name, connection string, service id). Measure fork time and note any free-tier limits on services/forks.
2. **Run the app on a Tiger service.** Create a service, set `DATABASE_URL` / `EVAL_ADMIN_URL` (with `?sslmode=require`), and run `make migrate seed`. Expect and fix differences from local Docker:
   - extension availability (`vectorscale`, `pg_textsearch` - the spec's fallbacks are tsvector + pgvector HNSW behind `search/hybrid.py`; BM25 syntax needs the schema-qualified index name `'ai.ae_terms_bm25'`);
   - role creation and `GRANT`s in migration 009 (managed services may not allow `CREATE ROLE` or a superuser `app_admin`); `SET LOCAL ROLE` needs the connecting user to be a member of each app role;
   - `CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)` must run outside a transaction (the migrator already uses autocommit);
   - `TRUNCATE`/reset behaviour and the golden snapshot (`golden` schema) on a managed service.
3. **Eval forks on Tiger.** With `FORK_BACKEND=tiger`, `make eval SCENARIO=smoke` must create a control fork and an injected fork from the golden service, run, score, and **always delete both** (check there is no leaked service after a failure).
4. **Optional, if you have time:** replace the transaction-based what-if/backtest (milestone 15) with real forks, keeping the existing implementation as the fallback.
5. Write `docs/TIGER.md`: setup steps, env vars, what differs from local Docker, and a cost/limits note.

## Acceptance
- `FORK_BACKEND=template` (local Docker) still works exactly as before: `make test` stays green.
- On Tiger: migrate, seed, `make demo`, and `make eval SCENARIO=smoke` all work, with fork seconds reported in the eval metrics.
- Anything you could not verify is listed in `docs/DECISIONS.md` under a "Tiger Cloud" heading.

## Constraints (see CLAUDE.md)
No API keys or connection strings with passwords in tracked files. Use your own Gemini key; the free tier is rate-limited, so run with `LLM_MODE=replay LLM_QUERY_DRAFTS=0`. Do not read `answer_key` from app code. Open a PR into `main`; do not push to `main` directly.
