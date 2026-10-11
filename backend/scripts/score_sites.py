"""Do the planted problem sites rank at the top of the rule score? (spec §9.7 'done when'). Reads answer_key as eval_admin."""
import pandas as pd
import psycopg

from app.config import get_settings


def main() -> None:
    with psycopg.connect(get_settings().eval_admin_url) as conn:
        day = conn.execute("SELECT max(sim_date) FROM ops.site_risk").fetchone()[0]
        scores = pd.read_sql("SELECT site_id, rule_score, model_score FROM ops.site_risk WHERE sim_date = %s", conn, params=(day,))
        truth = pd.read_sql("SELECT site_id, personality FROM answer_key.site_personality", conn)
    df = scores.merge(truth, on="site_id")
    df["planted"] = df.personality != "normal"
    n_planted = int(df.planted.sum())
    print(f"as of {day}: {len(df)} sites, {n_planted} planted problem sites")
    for col in ("rule_score", "model_score"):
        if df[col].notna().any():
            top = df.sort_values(col, ascending=False)
            for k in (n_planted, 12, 15):
                hit = int(top.head(k).planted.sum())
                print(f"  {col} top-{k}: precision {hit / k:.0%} recall {hit / n_planted:.0%}")
    print(df.sort_values("rule_score", ascending=False)[["site_id", "personality", "rule_score", "model_score"]].head(14).to_string(index=False))


if __name__ == "__main__":
    main()
