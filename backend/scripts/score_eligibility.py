"""Print the eligibility assistant's scores (see app/evals/protocol_eval.py). Runs as eval_admin."""
import psycopg

from app.config import get_settings
from app.evals.protocol_eval import score


def main() -> None:
    s = get_settings()
    with psycopg.connect(s.database_url) as app, psycopg.connect(s.eval_admin_url) as key:
        r = score(app, key)
    print(f"{r['n']} questions: accuracy on answerable {r['accuracy']:.0%}; escalation precision {r['escalation_precision']:.0%}, recall {r['escalation_recall']:.0%}")
    for m in r["misses"]:
        print("  missed:", m)


if __name__ == "__main__":
    main()
