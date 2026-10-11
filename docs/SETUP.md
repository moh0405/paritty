# Setting up Paritty from a clean machine

For every contributor and every Claude Code session. Follow part A to run everything locally; parts B and C are only needed for live Gemini calls and for Tiger Cloud. Nothing in this file is a secret, and no secret ever goes into a tracked file: keys and passwords live only in `.env` (gitignored) and in your system keyring.

Commands were run on macOS (Apple silicon) on 2026-10-11. Linux should work the same way with your package manager in place of Homebrew; that was not tested.

## A. Local setup (no keys, no accounts)

### 1. Tools
| Tool | Version used | Install |
|---|---|---|
| Docker Desktop | 29 | docker.com; **start it** before `make db` |
| uv | current | `brew install uv` (it installs Python 3.12 for the project by itself) |
| Node.js | 22 or newer (CI uses 22) | `brew install node` |
| psql | any | `brew install postgresql@15` - only for the manual database commands below |
| GitHub CLI | any | `brew install gh`, then `gh auth login` |

### 2. Clone and configure
```
git clone https://github.com/moh0405/parity lockstep && cd lockstep     # the repository was renamed; the old lockstep URL still redirects
cp .env.example .env
```
The defaults in `.env` are the local setup; leave them alone for part A.

### 3. Build everything
```
make setup      # uv sync (backend) and npm ci (frontend)
make db         # TimescaleDB in Docker on localhost:5433 (5433, not 5432, to stay clear of a local Postgres)
make migrate    # applies backend/app/db/migrations in order
make seed       # downloads the public CDISC pilot data, builds the 24-site study, trains the site risk model, snapshots the golden template
```
`make seed` needs internet access for the download and takes a few minutes. It ends with a table of row counts and "golden template database ready".

### 4. Run and check
```
make demo       # API on http://localhost:8000, web on http://localhost:3000
make test       # backend tests
cd frontend && npx next typegen && npx tsc --noEmit && npm run lint
```
In the web app, the header buttons `+1 day / +7 days / +30 days` advance the simulated trial. `make reset` returns to the seeded state (study day 60).

Local passwords (`lockstep`) are development defaults for a database that only listens on your machine. Do not reuse them anywhere else.

### 5. After every `git pull`
```
make setup && make migrate && make golden
```
`make golden` resets the simulation to day 60 and rebuilds the template that evals and tests copy. If the model score column is empty on the Sites page, the model file is missing (it is gitignored): `cd backend && uv run python -m scripts.train_risk_model`.

### 6. Your own database
Do not run resets, long simulations or the full test suite against a database someone else (or your own running demo) is using. Copy the golden template and point at the copy for that shell only:
```
PGPASSWORD=lockstep psql -h localhost -p 5433 -U app_admin -d postgres -c "CREATE DATABASE mydev TEMPLATE lockstep_golden"
export DATABASE_URL=postgresql://app_admin:lockstep@localhost:5433/mydev
export EVAL_ADMIN_URL=postgresql://eval_admin:lockstep@localhost:5433/mydev
```
Environment variables win over `.env`, so this is also how to run locally while `.env` points at Tiger. Drop the copy when done: `DROP DATABASE mydev WITH (FORCE)`.

## B. Gemini API key (optional)

The default `LLM_MODE=replay` serves recorded responses from `backend/fixtures/llm_cache` and falls back to templates, so **no key is needed** to run, test or demo. A key is only needed for `LLM_MODE=live` or `LLM_MODE=record`.

1. Create a key in Google AI Studio (aistudio.google.com, "Get API key"). Each person uses their own.
2. Put it in `.env` as `GEMINI_API_KEY=...`. Never in a commit, an issue, a PR or a chat message.
3. The free tier is rate-limited (a drafted query takes about 15 s). For tests and ordinary development keep `LLM_MODE=replay LLM_QUERY_DRAFTS=0`. Do not record fixtures unless asked (CLAUDE.md).

## C. Tiger Cloud (optional)

Only needed to run the app or the evals on Tiger. Details, measurements and limits are in `docs/TIGER.md`; this is the exact sequence.

**Each person uses their own Tiger account and project.** The `lockstep-golden` service used for the measurements belongs to one contributor's project; nobody else can reach it, and credentials are not shared.

### 1. CLI and login
```
brew install --cask timescale/tap/tiger-cli
tiger auth login          # opens a browser; a person has to do this step
tiger auth status
```
The CLI keeps its session in the system keyring. Paritty itself never reads a Tiger API key: the eval harness shells out to the `tiger` command. For a machine with no browser, create a key pair in the Tiger console (Settings) and run `tiger auth login --public-key <key> --secret-key <secret>`, or export `TIGER_PUBLIC_KEY` and `TIGER_SECRET_KEY` first. Those keys are secrets: keep them out of the repository and out of `.env.example`.

### 2. A service for Paritty only
```
tiger service create --name lockstep-golden --cpu shared --no-set-default
tiger service list        # note the 10-character service id
```
Never reuse a service that holds other data: every eval fork copies the whole service and `make reset` truncates Paritty's tables. **The free plan allows two services per project**, and an eval needs one free slot for its fork.

The service's `tsdbadmin` password is saved to your keyring when the service is created. If it is lost: `tiger service update-password <id> --auto-generate` (anything else using that service must then be updated).

### 3. `.env` for Tiger
```
tiger db uri <id> --with-password        # prints the DATABASE_URL, password included: do not paste it anywhere but .env
openssl rand -hex 20                     # a password for eval_admin
```
```
DATABASE_URL=postgresql://tsdbadmin:<password>@<host>:<port>/tsdb?sslmode=require
EVAL_ADMIN_URL=postgresql://eval_admin:<the generated password>@<host>:<port>/tsdb?sslmode=require
GOLDEN_SERVICE_ID=<service id>
FORK_BACKEND=tiger
```

### 4. Create `eval_admin` before migrating
A Tiger service is reachable from the internet, and migration 009 would otherwise create this role with the local development password. This command reads the password from `.env`, so nothing is typed or printed:
```
set -a && . ./.env && set +a && psql "$DATABASE_URL" -c "CREATE ROLE eval_admin LOGIN PASSWORD '$(python3 -c "import os,urllib.parse as u;print(u.urlparse(os.environ['EVAL_ADMIN_URL']).password)")'"
```

### 5. Build and run
```
make setup migrate seed     # make db is a no-op when .env says FORK_BACKEND=tiger
make demo
LLM_MODE=replay LLM_QUERY_DRAFTS=0 make eval SCENARIO=smoke
tiger service list          # afterwards: only the golden service should remain
```
The smoke eval took 13 minutes on Tiger (about 1 minute locally). Checked on Tiger so far: migrations 001-014, `make seed` and the smoke eval. **Not checked on Tiger: migrations 015 and later, `make demo`, the test suite** (see "Tiger Cloud" in `docs/DECISIONS.md`).

While `.env` points at Tiger, every `make` target talks to Tiger. To work locally in the same checkout, export the local `DATABASE_URL`, `EVAL_ADMIN_URL` and `FORK_BACKEND=template` in your shell (part A, step 6).

## D. Notes for Claude Code sessions

- Read `CLAUDE.md` (rules), `CONTRIBUTING.md` (branches, migration ranges) and `docs/WORKSPLIT.md` (who owns what) before changing anything. Check the GitHub issues for your assignment.
- **Steps a person must do**: `tiger auth login` (browser), creating a database role with a password (part C, step 4), and merging a pull request that has no review. The permission system stops an agent at these; ask the person to run the command rather than looking for another route.
- Tiger tools inside Claude Code: `tiger mcp install`, then restart the session or reconnect with `/mcp`. The CLI through the shell does the same things without it.
- Browser checks need the Claude in Chrome extension connected. Say "not viewed" in the PR if it was not.
- Parallel work in one clone: use `git worktree add ../lockstep-<topic> -b <branch> main`. Run `npm ci` inside the worktree; a symlinked `node_modules` makes the Next.js dev server fail. Give the worktree its own `.env` and its own database copy.
- Never print a connection string with its password into the conversation or a log; mask it (`sed -E 's#://([^:]+):[^@]+@#://\1:<hidden>@#'`).

## E. When something goes wrong

| Symptom | Cause and fix |
|---|---|
| `failed to connect to the docker API` | Docker Desktop is not running. Start it, then `make db`. |
| `npm ci` says the lock file is out of sync | `package.json` changed without the lock file. Run `npm install` in `frontend/` and commit `package-lock.json`. |
| `tsc`: `Cannot find name 'LayoutProps'` | Route types are generated: run `npx next typegen` first (CI does). |
| `source database "lockstep_golden" is being accessed by other users` | A TimescaleDB background worker is briefly attached to the template. Run the command again. It can also fail a fork test once; rerun the test. |
| API health says `terminating connection due to administrator command` | `make golden` ends other sessions on the main database. Restart the API. |
| Many tests fail on a database you have advanced | Some tests assume the seeded state. Run the suite on a fresh copy of the golden template (part A, step 6). |
| Sites page shows no model score | `backend/models/site_risk.joblib` is missing: `cd backend && uv run python -m scripts.train_risk_model`, then advance the clock. |
| Pages load but show errors | The web server is up and the API is not. `make demo` starts both; check http://localhost:8000/api/health. |
| `You have reached your free service limit` | Tiger free plan: two services. Delete a service you no longer need, or use local forks (`FORK_BACKEND=template`). |
| `password authentication failed` on Tiger | `tiger db save-password` only stores what you type; it does not change the service. Use `tiger service update-password <id> --auto-generate`. |
