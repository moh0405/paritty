# Contributing

Two people (and their Claude Code sessions) work in this repo at the same time. These rules keep that smooth.

## Branches and pull requests
- Never commit straight to `main`. Branch as `feat/<milestone>-<topic>` (for example `feat/m12-eligibility-assistant`) or `fix/<topic>`.
- Keep PRs small and focused; rebase on `main` before opening (`git fetch && git rebase origin/main`).
- A PR needs: passing CI, an entry in `docs/DECISIONS.md` for any deviation, and tests for new logic. The other contributor reviews.
- Squash-merge, and delete the branch.

## Avoiding collisions
- **Migrations**: `001-099` main line; contributor A uses `100-199`, contributor B uses `200-299`. Check `backend/app/db/migrations/` for the highest number before adding one. If you add a migration, say so in the PR: others must run `make migrate` and rebuild the golden template (`make golden`).
- **Hot files** that everyone touches: `backend/app/sim/daily_cycle.py`, `backend/app/main.py`, `frontend/components/Header.tsx`, `frontend/lib/api.ts`, `docs/DECISIONS.md`. Add to them in small, separate hunks (one router line, one nav link) and merge often.
- **Split work by milestone or module**, not by file. Agree who owns what in an issue before starting.

## Secrets and data
- `.env` is gitignored. Never commit API keys; each person uses their own Gemini key. Do not paste keys into issues, PRs or commit messages.
- Only public or synthetic data. Large files and raw downloads (`data/raw/`) stay out of git.

## Before you push
```
make test
cd frontend && npx tsc --noEmit && npm run lint
```
Use `LLM_MODE=replay` and your own database (see CLAUDE.md). Commit messages: a short summary line, a body explaining why, and the `Co-Authored-By` trailer your Claude session adds.
