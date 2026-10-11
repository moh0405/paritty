"""Medical review signals (spec §9.6). Detection is deterministic; wording is neutral ("potential", "needs review")."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import product

import numpy as np
from scipy import stats

ALT_AST_X, BILI_X, HYS_WINDOW_DAYS = 3.0, 2.0, 30


@dataclass(frozen=True)
class LabPoint:
    id: int
    test: str
    day: date
    x_uln: float
    grade: int | None = None


@dataclass
class HysResult:
    usubjid: str
    aminotransferase: LabPoint            # the ALT/AST point at or above 3x ULN
    bilirubin: LabPoint                   # the bilirubin point at or above 2x ULN
    alp_x_uln: float | None               # ALP near the peak, for context
    days_apart: int

    @property
    def wording(self) -> str:
        return "Potential Hy's Law pattern - requires medical review"


def hys_law(usubjid: str, points: list[LabPoint]) -> HysResult | None:
    """ALT or AST at or above 3x ULN with total bilirubin at or above 2x ULN within 30 days. Picks the most extreme qualifying pair."""
    ast = [p for p in points if p.test in ("ALT", "AST") and p.x_uln >= ALT_AST_X]
    bil = [p for p in points if p.test == "BILI" and p.x_uln >= BILI_X]
    best: tuple[float, LabPoint, LabPoint] | None = None
    for a, b in product(ast, bil):
        gap = abs((a.day - b.day).days)
        if gap <= HYS_WINDOW_DAYS and (best is None or a.x_uln * b.x_uln > best[0]):
            best = (a.x_uln * b.x_uln, a, b)
    if best is None:
        return None
    _, a, b = best
    alp = [p.x_uln for p in points if p.test == "ALP" and abs((p.day - a.day).days) <= HYS_WINDOW_DAYS]
    return HysResult(usubjid, a, b, max(alp) if alp else None, abs((a.day - b.day).days))


def edish_quadrant(peak_ast_alt: float | None, peak_bili: float | None) -> str:
    """eDISH quadrant by peak aminotransferase and bilirubin multiples of ULN (labels are descriptive, not diagnoses)."""
    a, b = peak_ast_alt or 0.0, peak_bili or 0.0
    if a >= ALT_AST_X and b >= BILI_X:
        return "potential Hy's Law pattern"
    if a >= ALT_AST_X:
        return "aminotransferase elevation"
    if b >= BILI_X:
        return "bilirubin elevation"
    return "within thresholds"


def peak(points: list[LabPoint], *tests: str) -> LabPoint | None:
    c = [p for p in points if p.test in tests]
    return max(c, key=lambda p: p.x_uln) if c else None


def edish_row(usubjid: str, site_id: str, points: list[LabPoint]) -> dict | None:
    alt, ast, bili = peak(points, "ALT"), peak(points, "AST"), peak(points, "BILI")
    if bili is None or (alt is None and ast is None):
        return None
    amino = max((p for p in (alt, ast) if p), key=lambda p: p.x_uln)
    return {"usubjid": usubjid, "site_id": site_id, "peak_alt": alt.x_uln if alt else None, "peak_ast": ast.x_uln if ast else None,
            "peak_amino": amino.x_uln, "peak_bili": bili.x_uln, "quadrant": edish_quadrant(amino.x_uln, bili.x_uln),
            "amino_lab_id": amino.id, "bili_lab_id": bili.id}


# ---- site ALT creep ---------------------------------------------------------------------------------
def subject_slope(days: list[float], xs: list[float]) -> float | None:
    """OLS slope of x_uln against study day (per day); None with fewer than 4 points or no spread in time."""
    if len(days) < 4 or len(set(days)) < 2:
        return None
    return float(np.polyfit(days, xs, 1)[0])


def robust_z(values: dict[str, float], min_scale: float = 1e-9) -> dict[str, float]:
    """(value - median) / (1.4826 * MAD), with a floor so a flat population does not divide by zero."""
    if len(values) < 3:
        return {k: 0.0 for k in values}
    v = np.array(list(values.values()))
    med = float(np.median(v))
    scale = max(1.4826 * float(np.median(np.abs(v - med))), min_scale, 0.1 * abs(med))
    return {k: (x - med) / scale for k, x in values.items()}


@dataclass
class CreepResult:
    site_id: str
    median_slope: float
    z: float
    n_subjects: int


def site_creep(slopes_by_site: dict[str, list[float]], min_subjects: int = 5, z_cut: float = 3.0) -> list[CreepResult]:
    med = {s: float(np.median(v)) for s, v in slopes_by_site.items() if len(v) >= min_subjects}
    z = robust_z(med)
    return [CreepResult(s, med[s], z[s], len(slopes_by_site[s])) for s in med if z[s] > z_cut]


# ---- rare AE clusters -------------------------------------------------------------------------------
@dataclass
class ClusterResult:
    site_id: str
    term: str
    count: int
    expected: float
    p_value: float
    other_rate: float


def rare_ae_clusters(term_counts: dict[tuple[str, str], int], site_subjects: dict[str, int], rare_rate: float = 0.01,
                     p_cut: float = 0.001, min_count: int = 3) -> list[ClusterResult]:
    """term_counts[(site, term)] = subjects at that site with the term. Rare = study rate elsewhere below 1%;
    Poisson test of the site's count against the rate seen at the other sites (smoothed so a term seen nowhere else is not 'rate 0')."""
    total_subjects = sum(site_subjects.values())
    out = []
    for (site, term), n in term_counts.items():
        if n < min_count:
            continue
        others = sum(c for (s, t), c in term_counts.items() if t == term and s != site)
        other_n = total_subjects - site_subjects.get(site, 0)
        rate = (others + 0.5) / (other_n + 1)
        if rate >= rare_rate:
            continue
        expected = rate * site_subjects.get(site, 0)
        p = float(stats.poisson.sf(n - 1, expected))
        if p < p_cut:
            out.append(ClusterResult(site, term, n, expected, p, rate))
    return sorted(out, key=lambda c: c.p_value)


# ---- AE-lab links ----------------------------------------------------------------------------------
@dataclass
class AeLabLink:
    usubjid: str
    lab: LabPoint
    previous_grade: int
    ae_id: int
    ae_term: str
    ae_onset: date
    days_apart: int


def ae_lab_links(usubjid: str, labs: list[LabPoint], aes: list[tuple[int, str, date]], window: int = 7) -> list[AeLabLink]:
    """AE onset within +/-7 days of a lab grade increase (to grade 2 or higher), same subject."""
    out = []
    by_test: dict[str, list[LabPoint]] = {}
    for p in sorted(labs, key=lambda p: p.day):
        by_test.setdefault(p.test, []).append(p)
    for series in by_test.values():
        prev_grade = 0
        for p in series:
            g = p.grade or 0
            if g > prev_grade and g >= 2:
                for ae_id, term, onset in aes:
                    d = (onset - p.day).days
                    if abs(d) <= window:
                        out.append(AeLabLink(usubjid, p, prev_grade, ae_id, term, onset, d))
            prev_grade = g
    return out


# ---- ranked review list -----------------------------------------------------------------------------
SCORES = {"hys_law": 100, "lab_grade4": 80, "lab_grade3": 60, "site_creep": 50, "ae_cluster": 50, "ae_lab_link": 30}


def recency_points(event_day: date, today: date) -> float:
    """0-10 points, decaying with age so the newest signals sort first within a score."""
    return round(10 * math.exp(-max(0, (today - event_day).days) / 30), 2)


@dataclass
class ReviewItem:
    type: str
    score: float
    title: str
    event_day: date
    usubjid: str | None = None
    site_id: str | None = None
    detail: dict = field(default_factory=dict)
    finding_key: str = ""


def rank(items: list[ReviewItem], today: date) -> list[ReviewItem]:
    for it in items:
        it.score = SCORES[it.type] + recency_points(it.event_day, today)
    return sorted(items, key=lambda i: -i.score)
