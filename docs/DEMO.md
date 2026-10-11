# Demo script (recorded AI answers, no key needed)

The AI text in this demo was written by Gemini once and saved in `backend/fixtures/llm_cache`. In the default `LLM_MODE=replay` the app reads those saved answers, so the demo needs no API key, no internet and costs nothing. A saved answer is found only when the app asks **exactly the same question** as when it was recorded, so follow the path below: start from a reset, advance 30 days, then use the listed actions.

Recorded on 2026-10-11 with `gemini-flash-latest`, seed 42, study days 60 to 90.

## Get ready (once, before the audience arrives)
```
export DATABASE_URL=postgresql://app_admin:lockstep@localhost:5433/tsdb      # skip these three lines if .env already points at local Docker
export EVAL_ADMIN_URL=postgresql://eval_admin:lockstep@localhost:5433/tsdb
export FORK_BACKEND=template
make db
cd backend && uv run python -W ignore -m scripts.build_protocol && cd ..     # loads the current protocol text
make reset                                                                   # back to study day 60
make demo                                                                    # http://localhost:3000
```
Do not set `LLM_QUERY_DRAFTS=0` and leave "auto-approve" ticked: both change what the app asks.

## The path
1. **Today** (`/today`): what is waiting for a person. Start the tour here if the audience is new to the domain.
2. Press **+30 days** in the top bar (study day 90). About 50 queries are written during these days; 51 of the 53 carry Gemini's wording, each checked against the database cell it cites.
3. **Queries to sites**: open a query's evidence. Translate one of the first six rows to **Spanish** or **French**.
4. **Safety report matching**: open a pair and run the causality assessment (the first three pairs are recorded).
5. **Site risk**, then **Visit plan**: press *Draft agenda* or *Draft letter* for one of the first six sites. Nine of these twelve drafts are Gemini's, verified; three fall back to the template because the draft did not pass verification. Approve one and open the site page to see the issues it created.
6. **Data checks**, "generated" tab: propose checks from the protocol.
7. **Ask the protocol**: type one of the recorded questions below.
8. **Data hub**: ask one of the recorded questions below.
9. **Lock readiness**: the forecast and what holds it back; run a what-if.

### Recorded questions (type them exactly)
Ask the protocol:
- How long do we have to answer a query?
- What is the allowed window for the Week 8 visit?
- Our candidate scored 15 on the Mini-Mental exam. Can we enroll?
- Is a candidate who previously took donepezil eligible?
- How soon must a serious adverse event be reported?
- When should study treatment be stopped because of liver tests?
- Which medications are prohibited during the study?
- My patient has chest pain today. Should I stop the study drug? *(shows a refusal to guess: the answer says the protocol does not cover it)*

Data hub:
- Which sites have the most open queries?
- How many subjects are enrolled at each site?
- Which sites have open critical queries?
- How many open safety report differences does each site have?

## Off the path
Anything not recorded still works, with plainer text: a query gets the template wording, an unrecorded protocol question gets the matching passage quoted, an unrecorded Data hub question or translation says the AI service is not available. Past study day 90 nothing is recorded.

To let the app answer new things, set `GEMINI_API_KEY` in `.env` and start it with `LLM_MODE=record`: it uses the saved answers first, calls Gemini only for what it has not seen, and saves the new answer. That needs internet during the demo and costs a fraction of a cent per answer.

## Recording again
`LLM_MODE=record` with a key, on your own database copy (docs/SETUP.md, part A step 6): `uv run python -W ignore -m scripts.build_protocol`, then `uv run python -W ignore -m scripts.record_demo 30`, then run the on-demand actions above through the app at day 90. The first recording took about 15 minutes and used roughly 120,000 input and 42,000 output tokens. Anything that changes a prompt (a prompt file, the protocol text, the seed, the model name) makes the old recordings unreachable.
