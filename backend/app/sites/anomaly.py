"""Cross-site anomaly tests (spec §9.7). Each test compares a site with the rest of the study and returns a plain-English reason to look."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from psycopg import Connection
from scipy import stats

from app.sim.constants import ALT_MAX_ELIGIBLE_XULN, SBP_MAX_ELIGIBLE, VISIT_WINDOW_DAYS
from app.sim.schedule import SCHEDULE


@dataclass
class AnomalyResult:
    site_id: str
    test: str
    flagged: bool
    p_value: float | None            # None for tests judged on a ratio
    statistic: float
    feature: float                   # larger = more unusual; feeds the rule score and the risk model
    explanation: str
    detail: dict = field(default_factory=dict)


# ---- pure statistics ---------------------------------------------------------------------------------
def terminal_digit_test(values: list[float], min_n: int = 50) -> tuple[float, float, list[int]] | None:
    """Chi-square of the last digit against a uniform distribution. Returns (chi2, p, counts per digit 0-9)."""
    digits = [int(round(v)) % 10 for v in values]
    if len(digits) < min_n:
        return None
    counts = [Counter(digits).get(d, 0) for d in range(10)]
    chi2, p = stats.chisquare(counts)
    return float(chi2), float(p), counts


def variance_ratio(site_sds: list[float], study_sds: list[float], min_subjects: int = 5) -> float | None:
    """Mean within-subject SD at the site over the mean in the whole study (values far below 1 look too regular)."""
    if len(site_sds) < min_subjects or not study_sds or np.mean(study_sds) == 0:
        return None
    return float(np.mean(site_sds) / np.mean(study_sds))


def duplicate_panels(panels: dict[tuple[str, str], tuple]) -> int:
    """panels[(usubjid, visit)] = tuple of readings. Returns how many panels are identical to another subject's panel."""
    by_panel: dict[tuple, set[str]] = defaultdict(set)
    for (u, _v), vec in panels.items():
        if len(vec) >= 6:
            by_panel[vec].add(u)
    return sum(len(s) for s in by_panel.values() if len(s) >= 2)


def underreporting(observed: int, patient_months: float, other_rate: float) -> tuple[float, float] | None:
    """Lower-tail Poisson probability of seeing this few events given the rate at the other sites. Returns (expected, p)."""
    if patient_months < 3 or other_rate <= 0:
        return None
    expected = other_rate * patient_months
    return expected, float(stats.poisson.cdf(observed, expected))


def timing_ks(site_offsets: list[float], other_offsets: list[float], min_n: int = 20) -> tuple[float, float] | None:
    if len(site_offsets) < min_n or len(other_offsets) < min_n:
        return None
    r = stats.ks_2samp(site_offsets, other_offsets)
    return float(r.statistic), float(r.pvalue)


def borderline_share(k: int, n: int, other_share: float, min_n: int = 8) -> tuple[float, float] | None:
    if n < min_n:
        return None
    return k / n, float(stats.binomtest(k, n, min(max(other_share, 0.01), 0.99), alternative="greater").pvalue)


def neg_log10(p: float | None, cap: float = 6.0) -> float:
    return 0.0 if p is None else min(cap, -math.log10(max(p, 1e-300)))


# ---- data access + assembly --------------------------------------------------------------------------------
def run_all(conn: Connection, today: date) -> dict[str, list[AnomalyResult]]:
    out: dict[str, list[AnomalyResult]] = defaultdict(list)

    # 1. terminal digit preference (blood pressure)
    by_site = defaultdict(list)
    for site, v in conn.execute("SELECT site_id, value FROM edc.vitals WHERE test_code IN ('SYSBP','DIABP') AND value IS NOT NULL"):
        by_site[site].append(v)
    for site, vals in by_site.items():
        r = terminal_digit_test(vals)
        if r:
            chi2, p, counts = r
            share = (counts[0] + counts[5]) / sum(counts)
            out[site].append(AnomalyResult(site, "terminal_digit", p < 0.001, p, chi2, neg_log10(p),
                f"Blood pressure readings end in 0 or 5 in {share:.0%} of {sum(counts)} readings (about 20% expected). Chi-square {chi2:.1f}, p = {p:.2g}; flagged below p = 0.001.",
                {"digit_counts": counts, "n": sum(counts)}))

    # 2. variance ratio (pulse)
    sds = defaultdict(list)
    for site, sd in conn.execute("SELECT site_id, stddev_samp(value) FROM edc.vitals WHERE test_code = 'PULSE' GROUP BY site_id, usubjid HAVING count(*) >= 4"):
        if sd is not None:
            sds[site].append(float(sd))
    study = [x for v in sds.values() for x in v]
    for site, v in sds.items():
        ratio = variance_ratio(v, study)
        if ratio is not None:
            out[site].append(AnomalyResult(site, "variance_ratio", ratio < 0.5, None, ratio, max(0.0, -math.log(max(ratio, 0.05))),
                f"Pulse varies within a subject by {ratio:.2f} times the study average (flagged below 0.5), across {len(v)} subjects.",
                {"ratio": ratio, "n_subjects": len(v)}))

    # 3. duplicated vitals panels
    panels: dict[str, dict] = defaultdict(dict)
    rows = conn.execute("SELECT site_id, usubjid, visit, test_code, value FROM edc.vitals WHERE test_code IN ('SYSBP','DIABP','PULSE') AND value IS NOT NULL "
                        "ORDER BY site_id, usubjid, visit, test_code, measured_at").fetchall()
    tmp: dict[tuple, list] = defaultdict(list)
    for site, u, visit, test, v in rows:
        tmp[(site, u, visit)].append((test, v))
    for (site, u, visit), vec in tmp.items():
        panels[site][(u, visit)] = tuple(vec)
    for site, pn in panels.items():
        n = duplicate_panels(pn)
        out[site].append(AnomalyResult(site, "duplicate_panels", n >= 2, None, float(n), float(n),
            f"{n} sets of vital signs are identical to another subject's set at this site (flagged at 2 or more)." if n else "No identical vital-sign sets across subjects.",
            {"duplicated_panels": n}))

    # 4. AE under-reporting
    pm = {s: float(m) for s, m in conn.execute("SELECT site_id, sum(GREATEST(0, COALESCE(discontinued_at, death_at, %s)::date - consent_at)) / 30.4375 FROM edc.subjects GROUP BY 1", (today,))}
    ae = {s: int(n) for s, n in conn.execute("SELECT site_id, count(*) FROM edc.ae GROUP BY 1")}
    tot_ae, tot_pm = sum(ae.values()), sum(pm.values())
    for site, m in pm.items():
        other_rate = (tot_ae - ae.get(site, 0)) / max(1e-9, tot_pm - m)
        r = underreporting(ae.get(site, 0), m, other_rate)
        if r:
            expected, p = r
            out[site].append(AnomalyResult(site, "ae_underreporting", p < 0.01 and ae.get(site, 0) < expected, p, ae.get(site, 0) / m, neg_log10(p) if ae.get(site, 0) < expected else 0.0,
                f"{ae.get(site, 0)} adverse events reported where about {expected:.0f} would be expected from the other sites' rate (p = {p:.2g}; flagged below 0.01).",
                {"observed": ae.get(site, 0), "expected": expected, "patient_months": m}))

    # 5. visit timing vs the rest of the study
    offs = defaultdict(list)
    for site, off in conn.execute("SELECT t.site_id, t.actual_date - (b.actual_date + t.planned_day - 1) FROM edc.visits t JOIN edc.visits b ON b.usubjid = t.usubjid "
                                  "AND b.visit = 'BASELINE' WHERE t.visit = ANY(%s)", ([v for v, _ in SCHEDULE],)):
        offs[site].append(float(off))
    for site, v in offs.items():
        other = [x for s, vals in offs.items() if s != site for x in vals]
        r = timing_ks(v, other)
        if r:
            d, p = r
            outside = sum(abs(x) > VISIT_WINDOW_DAYS for x in v) / len(v)
            out[site].append(AnomalyResult(site, "visit_timing", p < 0.01, p, d, neg_log10(p),
                f"Visit dates drift from the schedule differently from other sites (KS distance {d:.2f}, p = {p:.2g}); {outside:.0%} of {len(v)} visits fall outside the window.",
                {"ks": d, "outside_window": outside, "n": len(v)}))

    # 6. borderline eligibility values
    sbp = {(s, u): v for s, u, v in conn.execute("SELECT site_id, usubjid, value FROM edc.vitals WHERE test_code = 'SYSBP' AND visit = 'SCREENING 1' AND value IS NOT NULL ORDER BY measured_at DESC")}
    alt = {(s, u): x for s, u, x in conn.execute("SELECT site_id, usubjid, x_uln FROM edc.lab WHERE test_code = 'ALT' AND visit = 'SCREENING 1' AND x_uln IS NOT NULL")}
    subs = {(s, u) for s, u in list(sbp) + list(alt)}
    near = lambda v, cut: v is not None and 0.95 * cut <= v <= cut  # noqa: E731
    flag = {k: near(sbp.get(k), SBP_MAX_ELIGIBLE) or near(alt.get(k), ALT_MAX_ELIGIBLE_XULN) for k in subs}
    per_site = defaultdict(lambda: [0, 0])
    for (s, _u), f in flag.items():
        per_site[s][0] += f
        per_site[s][1] += 1
    k_all, n_all = sum(v[0] for v in per_site.values()), sum(v[1] for v in per_site.values())
    for site, (k, n) in per_site.items():
        r = borderline_share(k, n, (k_all - k) / max(1, n_all - n))
        if r:
            share, p = r
            out[site].append(AnomalyResult(site, "borderline_eligibility", p < 0.01, p, share, neg_log10(p),
                f"{k} of {n} screened subjects ({share:.0%}) have blood pressure or ALT within 5% of the eligibility limit (rest of study {(k_all - k) / max(1, n_all - n):.0%}); p = {p:.2g}.",
                {"borderline": k, "screened": n}))
    return out
