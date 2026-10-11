# LockStep
Continuous clean-to-lock copilot for clinical trials (HackRU 2026). See `LOCKSTEP_BUILD_SPEC.md`.

## Quick start
    cp .env.example .env
    make setup db migrate
    make demo        # api :8000, web :3000
    make test
