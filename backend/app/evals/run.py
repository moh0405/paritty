"""CLI: python -m app.evals.run --scenario full --repeats 1   (make eval SCENARIO=full REPEATS=1)"""
import argparse

from app.evals import harness, report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="smoke")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--advance-days", type=int, default=None, help="override the scenario length (backtest: days simulated before the forecast is made)")
    a = ap.parse_args()
    for run_id in harness.run_scenario(a.scenario, a.repeats, advance_days=a.advance_days):
        print(f"\n=== run {run_id} ({a.scenario}) ===")
        print(report.format_table(run_id))


if __name__ == "__main__":
    main()
