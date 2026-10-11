"""Agreement and kappa of AI causality assessments with the reference labels (needs Gemini results: LLM_MODE=live|record). Runs as eval_admin."""
import psycopg

from app.config import get_settings
from app.evals.causality_eval import score


def main() -> None:
    s = get_settings()
    with psycopg.connect(s.database_url) as app, psycopg.connect(s.eval_admin_url) as key:
        day = app.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
        r = score(app, key, day, sample=60)
        app.commit()
    print(r)
    if "agreement" not in r:
        print("No AI assessments yet (Gemini unavailable): every case fell back to the fact worksheet and was escalated, as designed.")


if __name__ == "__main__":
    main()
