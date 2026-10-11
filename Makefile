.PHONY: setup db migrate seed demo eval test reset record-llm score-checks golden
setup:
	cd backend && uv sync
	cd frontend && npm ci
db:   # local Docker only; on Tiger Cloud (FORK_BACKEND=tiger in .env) the database is the service in DATABASE_URL
	@if grep -q '^FORK_BACKEND=tiger' .env 2>/dev/null; then echo "Tiger Cloud: no local database to start"; else docker compose up -d db; fi
migrate:
	cd backend && uv run python -m app.db.migrate
seed:
	cd backend && uv run python -W ignore -m scripts.download_data \
	  && uv run python -W ignore -m scripts.build_golden \
	  && uv run python -W ignore -m scripts.scale_sites \
	  && uv run python -W ignore -m scripts.build_mock_systems \
	  && uv run python -W ignore -m scripts.plant_baseline \
	  && uv run python -W ignore -m scripts.finalize_golden \
	  && uv run python -W ignore -m scripts.build_protocol \
	  && uv run python -W ignore -m scripts.seed_search \
	  && uv run python -W ignore -m scripts.row_counts \
	  && uv run python -W ignore -m scripts.make_golden
# train_risk_model.py joins the seed chain in milestone 13
demo:
	cd backend && uv run uvicorn app.main:app --port 8000 & \
	cd frontend && npm run dev -- --port 3000
eval:
	cd backend && uv run python -W ignore -m app.evals.run --scenario $(or $(SCENARIO),smoke) --repeats $(or $(REPEATS),1)
golden:   # reset to the seeded state and snapshot it as the eval template database
	cd backend && uv run python -W ignore -m scripts.make_golden
test:
	cd backend && uv run pytest -q
reset:
	cd backend && uv run python -W ignore -m scripts.reset_sim
record-llm:   # needs GEMINI_API_KEY; free tier is slow (~15 s per drafted query), so expect minutes
	cd backend && LLM_MODE=record uv run python -W ignore -m scripts.build_protocol \
	  && LLM_MODE=record uv run python -W ignore -m scripts.seed_search \
	  && LLM_MODE=record uv run python -W ignore -m scripts.record_demo 60
score-checks:   # run after advancing the sim far enough that planted rows are released
	cd backend && uv run python -W ignore -m scripts.score_checks
