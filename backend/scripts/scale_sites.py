"""Scale to 24 sites, assign personalities, set entry lags (spec §7.2). Reads/rewrites edc_pending.*.

Personalities are written only to answer_key.site_personality. Idempotent: refuses to run twice.
"""
import json

import numpy as np
import pandas as pd

from app.medical.ctcae import GRADED_TESTS, grade_lab
from app.seed.common import RAW, connect, copy_df, fetch_df, rng
from app.sim.constants import ALT_MAX_ELIGIBLE_XULN, SBP_MAX_ELIGIBLE, VISIT_WINDOW_DAYS
from app.sim.personalities import NON_NORMAL, PARAMS, Personality

N_SITES_TOTAL = 24
SUBJECTS_PER_NEW_SITE = 14
TABLES = ["sites", "subjects", "ae", "lab", "vitals", "visits", "exposure", "conmeds", "medical_history", "subject_updates"]
DATE_COLS = {
    "subjects": ["consent_at", "first_dose_at", "discontinued_at", "death_at", "entered_at"],
    "ae": ["onset_at", "end_at", "entered_at"], "lab": ["collected_at", "entered_at"],
    "vitals": ["measured_at", "entered_at"], "visits": ["actual_date", "entered_at"],
    "exposure": ["start_at", "end_at", "entered_at"], "conmeds": ["start_at", "end_at", "entered_at"],
    "subject_updates": ["apply_on", "discontinued_at", "death_at"], "sites": [], "medical_history": [],
}
INT_COLS = {"subjects": ["age"], "ae": ["source_seq", "ctcae_grade"], "lab": ["ctcae_grade", "source_seq"], "visits": ["planned_day"]}
CITY_NAMES = ["Brightwater", "Calderfield", "Dovemont", "Eastharrow", "Fairlinden", "Greywick", "Hollowmere", "Ironvale"]
NEW_SITE_NAMES = ["Uplands Neuro Clinic", "Vexmoor Memory Center", "Wrenfield Cognitive Group", "Yarrowby Brain Institute",
                  "Zennor Valley Neurology", "Ashgrove Research Clinic", "Bellmarsh Memory Care"]


def load(conn) -> dict[str, pd.DataFrame]:
    out = {}
    for t in TABLES:
        df = fetch_df(conn, f"SELECT * FROM edc_pending.{t}").drop(columns=["id"], errors="ignore")
        if t == "subject_updates":
            df = df.drop(columns=["applied"])
        for c in DATE_COLS[t]:
            df[c] = pd.to_datetime(df[c])
        out[t] = df
    return out


def clone_subject(frames: dict[str, pd.DataFrame], src: str, new_id: str, site: str, offset: int,
                  r: np.random.Generator) -> dict[str, pd.DataFrame]:
    off = pd.Timedelta(days=offset)
    new: dict[str, pd.DataFrame] = {}
    for t in TABLES:
        if t == "sites":
            continue
        df = frames[t]
        part = df[df.usubjid == src].copy()
        part["usubjid"] = new_id
        if "site_id" in part:
            part["site_id"] = site
        for c in DATE_COLS[t]:
            part[c] = part[c] + off
        if t == "subjects":
            part["is_synthetic"] = True
        if t in ("lab", "vitals") and len(part):
            noisy = part.value * r.lognormal(0, 0.03, len(part))
            part["value"] = noisy.round(0) if t == "vitals" and str(part.unit.iloc[0]).lower() in ("mmhg", "beats/min") else noisy.round(2)
        if t == "lab" and len(part):
            part["x_uln"] = (part.value / part.uln).where(part.uln > 0)
            part["ctcae_grade"] = regrade(part)
        new[t] = part
    return new


def regrade(lab: pd.DataFrame) -> pd.array:
    return pd.array([grade_lab(t, v, u, l_, un) if t in GRADED_TESTS else None
                     for t, v, u, l_, un in zip(lab.test_code, lab.value, lab.uln, lab.lln, lab.unit)], dtype="Int64")


def apply_under_reporter(f: dict, subjects: set, r) -> None:
    ae = f["ae"]
    drop = ae.usubjid.isin(subjects) & ~ae.serious & (r.random(len(ae)) < 0.6)
    f["ae"] = ae[~drop]


def apply_too_perfect(f: dict, subjects: set, r) -> None:
    v = f["vitals"]
    bp = v.usubjid.isin(subjects) & v.test_code.isin(["SYSBP", "DIABP"]) & (r.random(len(v)) < 0.7)
    base = np.where(r.random(len(v)) < 0.5, 10, 5)
    v.loc[bp, "value"] = (v.value / base).round() * base
    pul = v.usubjid.isin(subjects) & v.test_code.eq("PULSE")
    mean = v[pul].groupby("usubjid").value.transform("mean")
    v.loc[pul, "value"] = (mean + 0.3 * (v.loc[pul, "value"] - mean)).round()
    # copy one vitals panel (visit) from one subject to two others
    sub = sorted(subjects)
    for visit in ("WEEK 8", "WEEK 4", "WEEK 12"):
        have = [s for s in sub if ((v.usubjid == s) & (v.visit == visit)).any()]
        if len(have) >= 3:
            src, targets = have[0], have[1:3]
            panel = v[(v.usubjid == src) & (v.visit == visit)].sort_values(["test_code", "measured_at"])
            panel["k"] = panel.groupby("test_code").cumcount()
            vals = {(t, k): x for t, k, x in zip(panel.test_code, panel.k, panel.value)}
            for tgt in targets:
                idx = v[(v.usubjid == tgt) & (v.visit == visit)].sort_values(["test_code", "measured_at"])
                for (code, k), (i, _) in zip(
                        zip(idx.test_code, idx.groupby("test_code").cumcount()), idx.iterrows()):
                    if (code, k) in vals:
                        v.at[i, "value"] = vals[(code, k)]
            break


def apply_rule_bender(f: dict, subjects: set, r) -> None:
    vis = f["visits"]
    cand = vis[vis.usubjid.isin(subjects) & vis.planned_day.notna() & (vis.planned_day > 1)]
    pick = cand[r.random(len(cand)) < 0.25]
    for i, row in pick.iterrows():
        delta = pd.Timedelta(days=int(r.choice([-1, 1])) * int(r.integers(VISIT_WINDOW_DAYS + 2, VISIT_WINDOW_DAYS + 10)))
        vis.at[i, "actual_date"] = row.actual_date + delta
        for t, col in (("lab", "collected_at"), ("vitals", "measured_at")):
            m = (f[t].usubjid == row.usubjid) & (f[t].visit == row.visit)
            f[t].loc[m, col] = f[t].loc[m, col] + delta
    # borderline eligibility: screening SBP / ALT sit within 5% of the cutoff
    v, lab = f["vitals"], f["lab"]
    for s in subjects:
        if r.random() < 0.6:
            m = (v.usubjid == s) & (v.visit == "SCREENING 1") & (v.test_code == "SYSBP")
            v.loc[m, "value"] = round(SBP_MAX_ELIGIBLE * float(r.uniform(0.95, 0.995)), 1)
            m = (lab.usubjid == s) & (lab.visit == "SCREENING 1") & (lab.test_code == "ALT") & (lab.uln > 0)
            lab.loc[m, "value"] = (lab.loc[m, "uln"] * ALT_MAX_ELIGIBLE_XULN * float(r.uniform(0.95, 0.995))).round(2)
    lab["x_uln"] = (lab.value / lab.uln).where(lab.uln > 0)
    lab["ctcae_grade"] = regrade(lab)


def main() -> None:
    r = rng(2)
    with connect() as conn:
        if conn.execute("SELECT count(*) FROM answer_key.site_personality").fetchone()[0]:
            raise SystemExit("scale_sites already ran (answer_key.site_personality is populated); rerun build_golden first")
        f = load(conn)
        # Remove the pilot's natural terminal-digit preference so the digit-preference anomaly test has a clean
        # baseline (otherwise unplanted real sites look as "round" as the planted ones). See docs/DECISIONS.md.
        v = f["vitals"]
        m = v.test_code.isin(["SYSBP", "DIABP", "PULSE"])
        v.loc[m, "value"] = v.loc[m, "value"] + r.integers(-4, 5, int(m.sum()))
        real_sites = sorted(f["sites"].site_id)
        new_sites = [f"9{i:02d}" for i in range(1, N_SITES_TOTAL - len(real_sites) + 1)]
        real_subjects = list(f["subjects"].usubjid)

        # ---- clone ---------------------------------------------------------------------------
        counter = 1
        clone_map: dict[str, str] = {}
        extra = {t: [] for t in TABLES if t != "sites"}
        site_rows = [dict(site_id=s, name=n, is_synthetic=True) for s, n in zip(new_sites, NEW_SITE_NAMES)]
        for site in new_sites:
            for src in r.choice(real_subjects, SUBJECTS_PER_NEW_SITE, replace=False):
                new_id = f"01-{site}-{counter:04d}"
                counter += 1
                clone_map[new_id] = str(src)
                part = clone_subject(f, src, new_id, site, int(r.integers(-20, 41)), r)
                for t, df in part.items():
                    extra[t].append(df)
        f["sites"] = pd.concat([f["sites"], pd.DataFrame(site_rows)], ignore_index=True)
        for t, parts in extra.items():
            f[t] = pd.concat([f[t], *parts], ignore_index=True)

        # ---- personalities ---------------------------------------------------------------------
        all_sites = list(f["sites"].site_id)
        order = list(r.permutation(all_sites))
        personality = {s: Personality.NORMAL for s in all_sites}
        for i, p in enumerate(NON_NORMAL):
            for s in order[2 * i: 2 * i + 2]:
                personality[s] = p
        by_site = f["subjects"].groupby("site_id").usubjid.apply(set).to_dict()
        for site, p in personality.items():
            subs = by_site.get(site, set())
            if p is Personality.UNDER_REPORTER:
                apply_under_reporter(f, subs, r)
            elif p is Personality.TOO_PERFECT:
                apply_too_perfect(f, subs, r)
            elif p is Personality.RULE_BENDER:
                apply_rule_bender(f, subs, r)

        # ---- entry lags ------------------------------------------------------------------------
        def lag_for(site_series: pd.Series) -> pd.Series:
            lo = site_series.map(lambda s: PARAMS[personality[s]].entry_lag[0]).to_numpy()
            hi = site_series.map(lambda s: PARAMS[personality[s]].entry_lag[1]).to_numpy()
            return pd.Series(r.integers(lo, hi + 1), index=site_series.index)

        basis = {"subjects": "consent_at", "ae": "onset_at", "lab": "collected_at", "vitals": "measured_at",
                 "visits": "actual_date", "exposure": "start_at", "conmeds": "start_at"}
        for t, col in basis.items():
            df = f[t]
            base = df[col].dt.tz_localize(None) if getattr(df[col].dt, "tz", None) is not None else df[col]
            df["entered_at"] = base.dt.normalize() + pd.to_timedelta(lag_for(df.site_id), unit="D")
        parent_entered = f["subjects"].set_index("usubjid").entered_at   # a child row never enters before its subject
        for t in basis:
            if t != "subjects":
                f[t]["entered_at"] = f[t].entered_at.where(f[t].entered_at >= f[t].usubjid.map(parent_entered), f[t].usubjid.map(parent_entered))
        site_of_subj = f["subjects"].set_index("usubjid").site_id
        up = f["subject_updates"]
        up["apply_on"] = up.apply_on - pd.Timedelta(days=2) + pd.to_timedelta(lag_for(up.usubjid.map(site_of_subj)), unit="D")

        # ---- write ----------------------------------------------------------------------------
        for t in TABLES:
            conn.execute(f"TRUNCATE edc_pending.{t} RESTART IDENTITY")
        for t in TABLES:
            df = f[t].copy()
            for c in DATE_COLS[t]:
                if c in ("collected_at", "measured_at"):
                    continue
                df[c] = pd.to_datetime(df[c]).dt.date
            for c in INT_COLS.get(t, []):
                df[c] = df[c].astype("Int64")
            if t == "ae":
                df = df.drop(columns=["updated_at"], errors="ignore")
            print(f"edc_pending.{t}: {copy_df(conn, 'edc_pending.' + t, df)} rows")
        copy_df(conn, "answer_key.site_personality",
                pd.DataFrame({"site_id": list(personality), "personality": [p.value for p in personality.values()]}))
        conn.commit()
    (RAW / "clone_map.json").write_text(json.dumps(clone_map))
    print({p.value: sorted(s for s, q in personality.items() if q is p) for p in Personality if p is not Personality.NORMAL})


if __name__ == "__main__":
    main()
