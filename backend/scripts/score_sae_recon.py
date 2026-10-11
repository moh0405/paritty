"""Score SAE reconciliation against planted discrepancies (spec §9.5 'done when'). Reads answer_key as eval_admin.
Run after advancing the sim so every planted case has appeared. Detection is judged on ops.check_failures, which persist after
a discrepancy is later fixed by a follow-up."""
from collections import defaultdict

import pandas as pd
import psycopg

from app.config import get_settings

EXPECT = {   # planted kind -> specs that count as a detection
    "sae_date_shift": {"sae_onset"}, "sae_synonym": {"sae_term"}, "sae_coded_change": {"sae_term"},
    "sae_causality_flip": {"sae_causality"}, "sae_seriousness_flip": {"sae_seriousness"},
    "sae_missing_outcome": {"sae_outcome"}, "sae_death_mismatch": {"sae_death"},
    "sae_edc_only": {"chk_22", "sae_fatal_one_sided"}, "sae_safety_only": {"sae_safety_only", "sae_fatal_one_sided"},
}
ALL_SPECS = {s for v in EXPECT.values() for s in v} | {"sae_outcome", "sae_death"}


def main() -> None:
    with psycopg.connect(get_settings().eval_admin_url) as conn:
        planted = pd.read_sql("SELECT kind, usubjid, src_pk, field, injected FROM answer_key.planted WHERE module = 'sae_recon'", conn)
        fails = pd.read_sql("SELECT check_id, usubjid FROM ops.check_failures WHERE check_id LIKE 'sae\\_%%' OR check_id = 'chk_22'", conn)
        decisions = pd.read_sql("SELECT same_event, method FROM ai.term_decisions", conn)
        hist = pd.read_sql("SELECT sim_date, counts FROM ops.sae_recon_history ORDER BY sim_date", conn)
        causality_ref = conn.execute("SELECT count(*) FROM answer_key.causality_reference").fetchone()[0]
    got = defaultdict(set)
    for u, c in zip(fails.usubjid, fails.check_id):
        got[u].add(c)
    rows, used = [], set()
    for _, p in planted.iterrows():
        expected_actionable = not (p.kind == "sae_synonym" or (p.kind == "sae_date_shift" and abs(int(p.injected)) <= 1))
        hit = bool(got[p.usubjid] & EXPECT[p.kind])
        if hit:
            used.add((p.usubjid, tuple(sorted(got[p.usubjid] & EXPECT[p.kind]))))
        rows.append(dict(kind=p.kind, expected="actionable" if expected_actionable else "acceptable", flagged=hit,
                         correct=hit if expected_actionable else not hit))
    df = pd.DataFrame(rows)
    act, acc = df[df.expected == "actionable"], df[df.expected == "acceptable"]
    tp = int(act.flagged.sum())
    planted_pairs = {(p.usubjid, s) for _, p in planted.iterrows() for s in EXPECT[p.kind]}
    fp_rows = [(u, c) for u, cs in got.items() for c in cs if (u, c) not in planted_pairs]
    print(df.groupby(["kind", "expected"]).agg(n=("correct", "size"), correct=("correct", "sum")).to_string())
    print(f"\nactionable recall: {tp}/{len(act)} = {tp / len(act):.0%}")
    print(f"acceptable handled correctly (not flagged): {int(acc.correct.sum())}/{len(acc)}  (synonym false-positive rate: "
          f"{1 - df[df.kind == 'sae_synonym'].correct.mean():.0%})")
    flagged = sum(len(cs) for cs in got.values())
    print(f"precision: {flagged - len(fp_rows)}/{flagged} = {(flagged - len(fp_rows)) / max(1, flagged):.0%}; unplanted flags: {len(fp_rows)} {fp_rows[:8]}")
    print(f"term decisions: {len(decisions)} {decisions.method.value_counts().to_dict() if len(decisions) else ''}; causality reference labels: {causality_ref}")
    if len(hist):
        first, last = hist.iloc[0], hist.iloc[-1]
        print(f"open discrepancies: {first.counts['open_discrepancies']} on {first.sim_date} -> {last.counts['open_discrepancies']} on {last.sim_date}")


if __name__ == "__main__":
    main()
