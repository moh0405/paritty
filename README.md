# LockStep
Continuous clean-to-lock copilot for clinical trials (HackRU 2026). See `LOCKSTEP_BUILD_SPEC.md`.

## Quick start
    cp .env.example .env
    make setup db migrate
    make demo        # api :8000, web :3000
    make test

## Running the simulation
    make reset                     # back to the seeded state at study day 60
    # in the UI header: +1d / +7d / +30d, or POST /api/sim/advance {"days": 30}
    make score-checks              # edit-check recall vs. planted errors (after a long advance)

## LLM modes
`LLM_MODE=replay` (default) serves recorded Gemini responses from `backend/fixtures/llm_cache`; a miss falls back to templates.
`LLM_MODE=record` calls Gemini and caches the response; `make record-llm` records the 60-day demo. `GEMINI_API_KEY` lives only in `.env` (gitignored).
