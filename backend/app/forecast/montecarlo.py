"""Lock-date Monte Carlo (spec §9.8): Kaplan-Meier resolution times, vectorized sampling, lock = latest completion + procedure days."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

LOCK_PROCEDURE_DAYS = 5
TAIL_MEAN_FLOOR = 7.0
MAX_DAYS = 365.0
SHRINK_EVENTS = 10


class KmSampler:
    """Samples a query's total time-to-close from a Kaplan-Meier curve, optionally conditioned on having been open for `age` days."""

    def __init__(self, durations: list[float], events: list[bool]):
        self.n_events = int(sum(events))
        self.t = np.array([0.0])
        self.s = np.array([1.0])
        self.tail_mean = TAIL_MEAN_FLOOR
        if len(durations) and self.n_events:
            from lifelines import KaplanMeierFitter
            km = KaplanMeierFitter().fit(durations, event_observed=events)
            sf = km.survival_function_
            self.t = np.concatenate([[0.0], sf.index.to_numpy(dtype=float)])
            self.s = np.concatenate([[1.0], sf.iloc[:, 0].to_numpy(dtype=float)])
            closed = [d for d, e in zip(durations, events) if e]
            self.tail_mean = max(TAIL_MEAN_FLOOR, float(np.mean(closed)))

    def sample(self, rng: np.random.Generator, size: int | tuple, age: np.ndarray | float = 0.0) -> np.ndarray:
        """Total times t with t > age (conditional survival): find the first t where S(t) <= u * S(age)."""
        age = np.broadcast_to(np.asarray(age, dtype=float), size) if not np.isscalar(age) or age else np.zeros(size)
        s_age = self.s[np.clip(np.searchsorted(self.t, age, side="right") - 1, 0, len(self.s) - 1)]
        target = rng.random(size) * s_age
        idx = np.searchsorted(-self.s, -target, side="left")           # s is non-increasing
        beyond = idx >= len(self.t)
        t = self.t[np.clip(idx, 0, len(self.t) - 1)]
        tail = np.maximum(self.t[-1], age) + rng.exponential(self.tail_mean, size)
        return np.minimum(np.where(beyond, tail, np.maximum(t, age + 0.5)), MAX_DAYS)


class MixtureSampler:
    """A site's curve shrunk toward the pooled curve: with fewer than 10 closed queries the site curve is used with probability n/10."""

    def __init__(self, site: KmSampler | None, pooled: KmSampler):
        self.site, self.pooled = site, pooled
        self.w = 0.0 if site is None else min(1.0, site.n_events / SHRINK_EVENTS)

    def sample(self, rng: np.random.Generator, size, age=0.0) -> np.ndarray:
        pooled = self.pooled.sample(rng, size, age)
        if self.site is None or self.w == 0:
            return pooled
        use_site = rng.random(size) < self.w
        return np.where(use_site, self.site.sample(rng, size, age), pooled)


@dataclass
class Items:
    """Work still needed before lock. Completion times are days after `today` (sampled per simulation)."""
    kind: list[str] = field(default_factory=list)          # open_query | expected_query | last_visit | enrollment
    site: list[str | None] = field(default_factory=list)
    category: list[str] = field(default_factory=list)      # ctq category, or 'visits' / 'enrollment'
    offset: list[float] = field(default_factory=list)      # fixed days from today before the item can start (future visit + entry lag)
    age: list[float] = field(default_factory=list)         # days already open (open queries)
    prob: list[float] = field(default_factory=list)        # chance the item materialises (expected queries)
    resolves: list[bool] = field(default_factory=list)     # whether a query resolution time is added after the offset

    def add(self, kind, site, category, offset=0.0, age=0.0, prob=1.0, resolves=True) -> None:
        self.kind.append(kind); self.site.append(site); self.category.append(category)
        self.offset.append(offset); self.age.append(age); self.prob.append(prob); self.resolves.append(resolves)

    def __len__(self) -> int:
        return len(self.kind)


@dataclass
class Simulation:
    completion: np.ndarray            # (n_sims, n_items) days after today; -inf for items that did not materialise
    lock: np.ndarray                  # (n_sims,) days after today


def simulate(items: Items, samplers: dict[str | None, MixtureSampler], pooled: MixtureSampler, rng: np.random.Generator, n_sims: int = 2000,
             enrollment: dict | None = None, response_override: dict[str, float] | None = None) -> Simulation:
    n = len(items)
    comp = np.full((n_sims, n), -np.inf)
    site = np.array(items.site, dtype=object)
    age, off, prob, res = (np.array(a, dtype=float) for a in (items.age, items.offset, items.prob, items.resolves))
    kind = np.array(items.kind)
    for s in set(items.site):
        cols = np.where(site == s)[0]
        cols_res = cols[res[cols] > 0]
        sampler = samplers.get(s, pooled)
        if cols_res.size:
            t = sampler.sample(rng, (n_sims, cols_res.size), age[cols_res])
            if response_override and s in response_override:       # what-if: this site answers in about N days (exponential)
                t = np.maximum(age[cols_res], rng.exponential(response_override[s], (n_sims, cols_res.size)) + 0.5)
            comp[:, cols_res] = off[cols_res] + (t - age[cols_res])
        cols_fix = cols[res[cols] <= 0]
        if cols_fix.size:
            comp[:, cols_fix] = off[cols_fix]
    exp_cols = np.where(prob < 1.0)[0]
    if exp_cols.size:
        happens = rng.random((n_sims, exp_cols.size)) < prob[exp_cols]
        comp[:, exp_cols] = np.where(happens, comp[:, exp_cols], -np.inf)
    if enrollment is not None and (kind == "enrollment").any():
        j = np.where(kind == "enrollment")[0][0]
        rate = enrollment["rate_per_day"] * rng.lognormal(0, 0.25, n_sims)          # uncertainty in the enrolment rate
        remaining = enrollment["remaining"]
        last_in = np.where(remaining > 0, remaining / np.maximum(rate, 1e-6), 0.0)
        comp[:, j] = last_in + enrollment["followup_days"] + enrollment["entry_lag"]
    lock = np.max(np.where(np.isfinite(comp), comp, 0.0), axis=1) + LOCK_PROCEDURE_DAYS if n else np.full(n_sims, float(LOCK_PROCEDURE_DAYS))
    return Simulation(comp, np.maximum(lock, LOCK_PROCEDURE_DAYS))


def percentiles(sim: Simulation) -> tuple[float, float, float]:
    p10, p50, p90 = np.percentile(sim.lock, [10, 50, 90])
    return float(p10), float(p50), float(p90)


def blockers(sim: Simulation, items: Items, top: int = 5) -> list[dict]:
    """Leave-one-site-out and leave-one-category-out change in P50 (same random draws, so differences are stable)."""
    base = float(np.percentile(sim.lock, 50))
    site = np.array(items.site, dtype=object)
    cat = np.array(items.category, dtype=object)
    out = []

    def without(mask: np.ndarray) -> float:
        keep = ~mask
        comp = sim.completion[:, keep]
        lock = (np.max(np.where(np.isfinite(comp), comp, 0.0), axis=1) if comp.shape[1] else 0.0) + LOCK_PROCEDURE_DAYS
        return float(np.percentile(np.maximum(lock, LOCK_PROCEDURE_DAYS), 50))

    for s in sorted({x for x in items.site if x}):
        d = base - without(site == s)
        if d > 0:
            out.append({"type": "site", "id": s, "delta_p50_days": round(d, 1), "items": int((site == s).sum())})
    for c in sorted(set(items.category)):
        d = base - without(cat == c)
        if d > 0:
            out.append({"type": "category", "id": c, "delta_p50_days": round(d, 1), "items": int((cat == c).sum())})
    return sorted(out, key=lambda b: -b["delta_p50_days"])[:top]
