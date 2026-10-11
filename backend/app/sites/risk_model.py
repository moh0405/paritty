"""Learned site risk score (spec §9.7). A gradient-boosted classifier is trained on *simulated* site histories
(`scripts/train_risk_model.py`), never on this study's answer key. It reads the same features as the rule score:
the capped robust z-scores from `risk.rule_scores`, so a site is always judged relative to the other sites in its study.

The simulator below re-creates the section 7.2 personalities as raw site data (blood pressures, visit offsets, adverse
event counts...) and pushes them through the same pure statistics as the live detectors in `anomaly.py`."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from statistics import median

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

from app.sim.constants import VISIT_WINDOW_DAYS
from app.sim.personalities import NON_NORMAL, PARAMS, Personality
from app.sites import anomaly
from app.sites.kris import KRI_DEFS, MIN_PATIENT_MONTHS

MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "site_risk.joblib"
ANOMALY_LABELS = {
    "terminal_digit": "Blood pressure terminal digits", "variance_ratio": "Pulse variability within subjects",
    "duplicate_panels": "Identical vital-sign sets", "ae_underreporting": "Fewer adverse events than expected",
    "visit_timing": "Visit timing against the schedule", "borderline_eligibility": "Eligibility values close to the limit",
}
FEATURES = [f"kri:{k}" for k in KRI_DEFS] + [f"anom:{a}" for a in ANOMALY_LABELS]
# Neutral names for what a site's data most resembles; a reason to look, never a conclusion about the site.
PATTERN_LABELS = {
    Personality.NORMAL: "no particular pattern", Personality.UNDER_REPORTER: "fewer adverse events than comparable sites",
    Personality.SLOPPY_ENTRY: "late or error-prone data entry", Personality.TOO_PERFECT: "unusually uniform measurements",
    Personality.RULE_BENDER: "visits or eligibility values near protocol limits", Personality.SLOW_RESPONDER: "slow query responses",
}
DEFAULT_STUDIES, SITES_PER_STUDY, HOLDOUT_STUDIES = 25, 24, 8      # 25 x 24 = 600 simulated site histories
TOP_CONTRIBUTIONS = 3


def feature_label(name: str) -> str:
    kind, key = name.split(":", 1)
    return KRI_DEFS[key]["label"] if kind == "kri" else ANOMALY_LABELS.get(key, key)


# ---- simulation (no database) ----------------------------------------------------------------------------
@dataclass
class _Site:
    personality: Personality
    patient_months: float
    ae: int
    sae: int
    points: int
    queries: int
    resolution: list[float]
    lags: list[int]
    subjects: int
    deviations: int
    offsets: list[float]
    screened: int
    screen_failed: int
    bp: list[float]
    pulse_sds: list[float]
    dup_panels: int
    borderline: int
    eligibility_n: int


def _simulate_site(r: np.random.Generator, pers: Personality, maturity: float) -> _Site:
    p = PARAMS[pers]
    n = int(r.integers(6, 22))
    visits = max(1, int(round(13 * maturity)))                      # scheduled visits seen so far per subject
    pm = n * 6.0 * maturity * float(r.uniform(0.7, 1.1))
    noise = lambda sd: float(r.lognormal(0, sd))                    # noqa: E731  natural between-site variation
    ae = int(r.poisson(0.9 * noise(0.3) * pm * (0.45 if pers is Personality.UNDER_REPORTER else 1.0)))
    points = n * visits * int(r.integers(20, 40))
    queries = int(r.poisson(points * 0.012 * p.error_multiplier * noise(0.3)))
    closed = int(queries * float(r.uniform(0.5, 0.9)))
    resolution = list(1 + r.lognormal(np.log(p.response_mean_days) - 0.125, 0.5, closed) * (1 + p.wrong_correction_rate))
    lags = list(r.integers(p.entry_lag[0], p.entry_lag[1] + 1, n * visits))
    dev_mult = {Personality.RULE_BENDER: 3.0, Personality.SLOPPY_ENTRY: 2.0}.get(pers, 1.0)
    offsets = r.normal(0, 4, n * visits) + np.where(r.random(n * visits) < 0.1, r.normal(0, 12, n * visits), 0)
    if pers is Personality.RULE_BENDER:
        bent = r.random(len(offsets)) < 0.25
        offsets = np.where(bent, r.choice([-1, 1], len(offsets)) * r.integers(VISIT_WINDOW_DAYS + 2, VISIT_WINDOW_DAYS + 10, len(offsets)), offsets)
    bp = r.integers(60, 180, n * visits * 6).astype(float)
    pulse_sds = r.lognormal(np.log(7), 0.3, n)
    dup = 2 if r.random() < 0.03 else 0
    if pers is Personality.TOO_PERFECT:
        rounded = r.random(len(bp)) < 0.7
        base = np.where(r.random(len(bp)) < 0.5, 10, 5)
        bp = np.where(rounded, np.round(bp / base) * base, bp)
        pulse_sds = pulse_sds * 0.3
        dup = 3 if maturity > 0.3 else dup                             # one set copied to two other subjects
    natural_borderline = float(r.uniform(0.04, 0.14))
    share = 0.6 + 0.4 * natural_borderline if pers is Personality.RULE_BENDER else natural_borderline
    extra_failures = int(r.integers(1, 6))
    failed_in_edc = int(r.binomial(n, float(r.uniform(0.05, 0.25))))
    return _Site(pers, pm, ae, int(r.poisson(0.04 * noise(0.3) * pm)), points, queries, resolution, [int(x) for x in lags], n,
                 int(r.poisson(0.5 * dev_mult * n)), [float(round(x)) for x in offsets], n + extra_failures, failed_in_edc + extra_failures,
                 list(bp), [float(x) for x in pulse_sds] if visits >= 4 else [], dup, int(r.binomial(n, share)), n)


def _features(sites: dict[str, _Site]) -> dict[str, dict[str, float]]:
    """The live feature definitions (kris.measure, anomaly.run_all) applied to simulated sites."""
    feats: dict[str, dict[str, float]] = {s: {} for s in sites}
    tot_ae, tot_pm = sum(x.ae for x in sites.values()), sum(x.patient_months for x in sites.values())
    study_sds = [sd for x in sites.values() for sd in x.pulse_sds]
    k_all, n_all = sum(x.borderline for x in sites.values()), sum(x.eligibility_n for x in sites.values())
    for s, x in sites.items():
        f = feats[s]
        if x.patient_months >= MIN_PATIENT_MONTHS:
            f["kri:ae_rate"] = x.ae / x.patient_months
            f["kri:sae_rate"] = x.sae / x.patient_months * 100
        if x.points:
            f["kri:query_rate"] = x.queries / x.points * 100
        if len(x.resolution) >= 3:
            f["kri:query_resolution_days"] = float(median(x.resolution))
        f["kri:entry_lag_days"] = float(median(x.lags))
        f["kri:deviations_per_patient"] = x.deviations / x.subjects
        f["kri:visit_window_violations"] = float(np.mean([abs(o) > VISIT_WINDOW_DAYS for o in x.offsets]))
        if x.screened >= 5:
            f["kri:screen_failure_rate"] = x.screen_failed / x.screened
        digit = anomaly.terminal_digit_test(x.bp)
        if digit:
            f["anom:terminal_digit"] = anomaly.neg_log10(digit[1])
        ratio = anomaly.variance_ratio(x.pulse_sds, study_sds)
        if ratio is not None:
            f["anom:variance_ratio"] = max(0.0, -float(np.log(max(ratio, 0.05))))
        f["anom:duplicate_panels"] = float(x.dup_panels)
        under = anomaly.underreporting(x.ae, x.patient_months, (tot_ae - x.ae) / max(1e-9, tot_pm - x.patient_months))
        if under:
            f["anom:ae_underreporting"] = anomaly.neg_log10(under[1]) if x.ae < under[0] else 0.0
        timing = anomaly.timing_ks(x.offsets, [o for t, y in sites.items() if t != s for o in y.offsets])
        if timing:
            f["anom:visit_timing"] = anomaly.neg_log10(timing[1])
        border = anomaly.borderline_share(x.borderline, x.eligibility_n, (k_all - x.borderline) / max(1, n_all - x.eligibility_n))
        if border:
            f["anom:borderline_eligibility"] = anomaly.neg_log10(border[1])
    return feats


def simulate_study(r: np.random.Generator, n_sites: int = SITES_PER_STUDY) -> tuple[dict[str, dict[str, float]], dict[str, Personality]]:
    """One simulated study: (capped robust z per feature per site, personality per site)."""
    from app.sites.risk import rule_scores
    n_problem = int(r.integers(n_sites // 6, n_sites // 2 + 1))
    problem = set(r.choice(n_sites, n_problem, replace=False).tolist())
    labels = {f"s{i:02d}": (NON_NORMAL[int(r.integers(0, len(NON_NORMAL)))] if i in problem else Personality.NORMAL) for i in range(n_sites)}
    maturity = float(r.uniform(0.2, 1.0))                             # how far the study has run: early data are thin
    sites = {s: _simulate_site(r, pers, maturity) for s, pers in labels.items()}
    return rule_scores(_features(sites))[1], labels


def to_matrix(zs: dict[str, dict[str, float]], sites: list[str]) -> np.ndarray:
    """Missing features stay NaN: the classifier handles them natively."""
    return np.array([[zs[s].get(f, np.nan) for f in FEATURES] for s in sites], dtype=float)


def _dataset(r: np.random.Generator, n_studies: int) -> tuple[np.ndarray, list[Personality], list[int]]:
    X, y, study = [], [], []
    for i in range(n_studies):
        zs, labels = simulate_study(r)
        order = sorted(labels)
        X.append(to_matrix(zs, order))
        y += [labels[s] for s in order]
        study += [i] * len(order)
    return np.vstack(X), y, study


# ---- training ---------------------------------------------------------------------------------------------
@dataclass
class RiskModel:
    binary: HistGradientBoostingClassifier         # problem pattern vs none
    multi: HistGradientBoostingClassifier          # which pattern
    importance: dict[str, float]                   # permutation importance on held-out simulated studies
    metrics: dict[str, float]
    seed: int
    n_sites: int


def _precision_at_k(prob: np.ndarray, truth: np.ndarray, study: list[int]) -> float:
    hits = total = 0
    ids = np.array(study)
    for i in set(study):
        m = ids == i
        k = int(truth[m].sum())
        if k:
            top = np.argsort(-prob[m])[:k]
            hits += int(truth[m][top].sum())
            total += k
    return hits / total if total else 0.0


def train(seed: int, n_studies: int = DEFAULT_STUDIES) -> RiskModel:
    r = np.random.default_rng(seed)
    X, y, _ = _dataset(r, n_studies)
    Xh, yh, study_h = _dataset(r, HOLDOUT_STUDIES)
    params = dict(max_iter=150, learning_rate=0.08, max_depth=3, l2_regularization=1.0, random_state=seed)
    yb, yhb = np.array([p is not Personality.NORMAL for p in y]), np.array([p is not Personality.NORMAL for p in yh])
    binary = HistGradientBoostingClassifier(**params).fit(X, yb)
    multi = HistGradientBoostingClassifier(**params).fit(X, [p.value for p in y])
    prob = binary.predict_proba(Xh)[:, 1]
    imp = permutation_importance(binary, Xh, yhb, n_repeats=5, random_state=seed, scoring="roc_auc")
    metrics = {"holdout_auc": float(roc_auc_score(yhb, prob)), "holdout_precision_at_k": _precision_at_k(prob, yhb, study_h),
               "holdout_pattern_accuracy": float(np.mean(multi.predict(Xh) == np.array([p.value for p in yh])))}
    return RiskModel(binary, multi, {f: float(v) for f, v in zip(FEATURES, imp.importances_mean)}, metrics, seed, len(y))


def save(model: RiskModel, path: Path = MODEL_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)


@lru_cache
def load(path: Path = MODEL_PATH) -> RiskModel | None:
    """None when the model has not been trained (`make seed` trains it); the rule score still works."""
    return joblib.load(path) if path.exists() else None


# ---- scoring ----------------------------------------------------------------------------------------------
@dataclass
class ModelScore:
    score: float                       # 0-100: how strongly the site's data resemble a simulated problem pattern
    pattern: str                       # Personality value of the most likely pattern
    pattern_label: str
    contributions: list[dict]          # features that raise the score most: {feature, label, z, effect}

    def as_dict(self) -> dict:
        """What is stored and shown: the neutral label only, never the simulator's internal pattern name."""
        return {"score": self.score, "pattern_label": self.pattern_label, "contributions": self.contributions}


def score_sites(zs: dict[str, dict[str, float]], model: RiskModel | None = None) -> dict[str, ModelScore]:
    """Score every site and say which features carry the score: each feature is set to 'typical' (z = 0) in turn and
    the drop in the model's probability is its effect."""
    model = model if model is not None else load()
    sites = sorted(s for s, z in zs.items() if z)
    if model is None or not sites:
        return {}
    X = to_matrix(zs, sites)
    prob = model.binary.predict_proba(X)[:, 1]
    pattern = model.multi.predict(X)
    effects = np.zeros_like(X)
    for j in range(len(FEATURES)):
        ablated = X.copy()
        ablated[:, j] = 0.0
        effects[:, j] = prob - model.binary.predict_proba(ablated)[:, 1]
    out: dict[str, ModelScore] = {}
    for i, s in enumerate(sites):
        top = [j for j in np.argsort(-effects[i])[:TOP_CONTRIBUTIONS] if effects[i, j] > 0.01 and not np.isnan(X[i, j])]
        out[s] = ModelScore(round(float(prob[i]) * 100, 2), str(pattern[i]), PATTERN_LABELS[Personality(pattern[i])],
                            [{"feature": FEATURES[j], "label": feature_label(FEATURES[j]), "z": round(float(X[i, j]), 2),
                              "effect": round(float(effects[i, j]) * 100, 1)} for j in top])
    return out
