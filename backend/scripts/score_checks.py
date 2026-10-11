"""Score the edit-check library against planted edit-check errors (spec §9.2 'done when').
Run after advancing the sim far enough that the planted rows have been released. Reads answer_key as eval_admin."""
import sys
from collections import defaultdict

import pandas as pd
import psycopg

from app.config import get_settings


def main() -> None:
    with psycopg.connect(get_settings().eval_admin_url) as conn:
        planted = pd.read_sql("SELECT kind, usubjid, src_table, src_pk, field FROM answer_key.planted WHERE module='checks'", conn)
        fails = pd.read_sql("SELECT check_id, usubjid, src_table, src_pk, resolved_on FROM ops.check_failures", conn)
        released = conn.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
    keys = set(zip(fails.src_table, fails.src_pk.astype(str)))
    visit_keys = {(u, p.split("|")[1]) for u, p in zip(fails.usubjid, fails.src_pk) if "|" in str(p)}
    hit = []
    for _, p in planted.iterrows():
        if p.kind == "missing_visit":
            hit.append((p.usubjid, p.field) in visit_keys)
        else:
            hit.append((p.src_table, str(p.src_pk)) in keys)
    planted["detected"] = hit
    by = planted.groupby("kind").detected.agg(["sum", "count"])
    by["recall"] = (by["sum"] / by["count"]).round(2)
    print(f"sim date {released}\n{by.to_string()}\n")
    rec = planted.detected.mean()
    planted_keys = set(zip(planted.src_table, planted.src_pk.astype(str))) | {(u, f) for u, f in zip(planted.usubjid, planted.field)}
    unplanted = fails[[(t, str(p)) not in planted_keys and (u, str(p).split("|")[-1]) not in planted_keys
                       for t, p, u in zip(fails.src_table, fails.src_pk, fails.usubjid)]]
    print(f"overall recall: {planted.detected.sum()}/{len(planted)} = {rec:.0%}")
    print(f"failures total {len(fails)}; on unplanted rows {len(unplanted)} ({len(unplanted)/max(1,len(fails)):.0%}) - "
          f"these are natural findings in the pilot data or genuine false alarms\n")
    print(unplanted.groupby("check_id").size().rename("unplanted").to_string())
    miss = planted[~planted.detected]
    if len(miss):
        print("\nmissed:\n" + miss.groupby("kind").size().to_string())


if __name__ == "__main__":
    main()
