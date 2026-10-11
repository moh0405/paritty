"""Recall of the baseline-planted central-lab differences after a simulation run (spec §9.4 'done when' >= 90%). Reads answer_key as eval_admin."""
import pandas as pd
import psycopg

from app.config import get_settings
from app.evals.scorer import EXPECT_LAB


def main() -> None:
    with psycopg.connect(get_settings().eval_admin_url) as c:
        planted = pd.read_sql("SELECT kind, usubjid FROM answer_key.planted WHERE module = 'lab_recon' AND scenario_run_id IS NULL", c)
        got = {(a, b) for a, b in c.execute("SELECT check_id, usubjid FROM ops.check_failures WHERE check_id IN ('chk_24','chk_25','chk_26')")}
        stale = c.execute("SELECT count(*) FROM ops.check_failures WHERE check_id = 'lab_stale_feed'").fetchone()[0]
        day = c.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
    rows = []
    for r in planted.itertuples():
        hit = stale > 0 if r.kind == "stale_feed" else any((c, r.usubjid) in got for c in EXPECT_LAB[r.kind])
        rows.append((r.kind, hit))
    df = pd.DataFrame(rows, columns=["kind", "hit"])
    print(f"as of {day}")
    print(df.groupby("kind").hit.agg(["sum", "count", "mean"]).round(2).to_string())
    print(f"overall recall: {int(df.hit.sum())}/{len(df)} = {df.hit.mean():.0%}")
    planted_pairs = {(c, r.usubjid) for r in planted.itertuples() if r.kind in EXPECT_LAB for c in EXPECT_LAB[r.kind]}
    extra = got - planted_pairs
    print(f"flags on subjects with no planted lab difference: {len(extra)} of {len(got)}")


if __name__ == "__main__":
    main()
