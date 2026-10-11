import numpy as np
import pytest

from app.forecast.montecarlo import Items, KmSampler, MixtureSampler, blockers, percentiles, simulate


def km(durations, events=None):
    return KmSampler(durations, events if events is not None else [True] * len(durations))


def mix(durations, events=None):
    return MixtureSampler(km(durations, events), km([5.0, 6.0, 7.0, 8.0, 9.0] * 4))


def test_km_samples_follow_the_observed_distribution():
    s = km([2, 4, 4, 6, 8, 10, 12, 14, 16, 18] * 5)
    t = s.sample(np.random.default_rng(0), 20000)
    assert 7.5 <= np.median(t) < 11.0 and t.min() >= 2 and t.max() <= 365


def test_conditioning_on_age_never_returns_less_than_age():
    s = km([2, 4, 6, 8, 10, 20, 30] * 5)
    t = s.sample(np.random.default_rng(1), 5000, age=15.0)
    assert (t > 15.0).all() and np.median(t) > np.median(s.sample(np.random.default_rng(1), 5000))


def test_censored_only_data_falls_back_to_the_tail_model():
    s = km([30.0, 40.0], [False, False])
    t = s.sample(np.random.default_rng(2), 1000)
    assert s.n_events == 0 and t.min() >= 0 and np.isfinite(t).all()


def test_site_curve_is_shrunk_toward_the_pooled_curve_when_data_are_thin():
    slow_site = KmSampler([40.0, 45.0], [True, True])                  # 2 events: weight 0.2
    pooled = km([5.0, 6.0, 7.0, 8.0, 9.0] * 4)
    m = MixtureSampler(slow_site, pooled)
    assert m.w == pytest.approx(0.2)
    med = np.median(m.sample(np.random.default_rng(3), 20000))
    assert med < 20 and med < np.median(MixtureSampler(KmSampler([40.0] * 12, [True] * 12), pooled).sample(np.random.default_rng(3), 20000))


def _items(n_open=5, age=3.0, site="A"):
    it = Items()
    for _ in range(n_open):
        it.add("open_query", site, "safety", age=age)
    return it


def test_more_open_items_push_the_p50_later():
    samplers = {"A": mix([3, 5, 8, 12, 20, 30] * 6)}
    pooled = samplers["A"]
    few = simulate(_items(2), samplers, pooled, np.random.default_rng(4))
    many = simulate(_items(60), samplers, pooled, np.random.default_rng(4))
    assert percentiles(many)[1] > percentiles(few)[1]


def test_simulation_is_deterministic_with_a_seed_and_percentiles_are_ordered():
    samplers = {"A": mix([3, 5, 8, 12, 20] * 6)}
    a = simulate(_items(10), samplers, samplers["A"], np.random.default_rng(7))
    b = simulate(_items(10), samplers, samplers["A"], np.random.default_rng(7))
    assert np.array_equal(a.lock, b.lock)
    p10, p50, p90 = percentiles(a)
    assert p10 <= p50 <= p90


def test_lock_includes_the_five_day_procedure_and_empty_work_locks_in_five_days():
    sim = simulate(Items(), {}, mix([5, 6]), np.random.default_rng(0))
    assert (sim.lock == 5).all()
    it = Items()
    it.add("last_visit", None, "visits", offset=30.0, resolves=False)
    assert (simulate(it, {}, mix([5, 6]), np.random.default_rng(0)).lock == 35).all()


def test_expected_queries_only_sometimes_materialise():
    it = Items()
    it.add("expected_query", "A", "efficacy", offset=10.0, prob=0.3)
    sim = simulate(it, {"A": mix([4, 5, 6] * 10)}, mix([4, 5, 6] * 10), np.random.default_rng(5), n_sims=4000)
    share = np.isfinite(sim.completion[:, 0]).mean()
    assert 0.25 < share < 0.35


def test_enrollment_item_uses_the_projected_last_patient_plus_followup():
    it = Items()
    it.add("enrollment", None, "enrollment", resolves=False)
    enr = {"rate_per_day": 1.0, "remaining": 50, "followup_days": 182, "entry_lag": 3}
    sim = simulate(it, {}, mix([5, 6]), np.random.default_rng(6), enrollment=enr)
    assert 182 + 3 + 5 + 30 < np.median(sim.lock) < 182 + 3 + 5 + 90


def test_blockers_name_the_slow_site_and_the_slow_category():
    fast, slow = mix([2, 3, 4] * 10), mix([60, 70, 80] * 10)
    it = Items()
    for _ in range(8):
        it.add("open_query", "FAST", "other", age=1.0)
    for _ in range(3):
        it.add("open_query", "SLOW", "safety", age=1.0)
    sim = simulate(it, {"FAST": fast, "SLOW": slow}, fast, np.random.default_rng(8))
    b = blockers(sim, it)
    assert b[0]["type"] in ("site", "category") and b[0]["id"] in ("SLOW", "safety") and b[0]["delta_p50_days"] > 20
    assert all(x["id"] != "FAST" for x in b if x["type"] == "site")


def test_response_override_speeds_up_a_site():
    slow = mix([40, 50, 60] * 10)
    it = _items(10)
    base = percentiles(simulate(it, {"A": slow}, slow, np.random.default_rng(9)))[1]
    fast = percentiles(simulate(it, {"A": slow}, slow, np.random.default_rng(9), response_override={"A": 3.0}))[1]
    assert fast < base - 10


def test_a_hypothetical_never_changes_the_underlying_draws_and_masking_only_removes_work():
    samplers = {"A": mix([3, 5, 8, 12, 20, 30] * 6), "B": mix([2, 4, 6] * 10)}
    it = Items()
    for site in ("A", "B", "A"):
        it.add("open_query", site, "safety" if site == "A" else "other", age=2.0)
    base = simulate(it, samplers, samplers["A"], np.random.default_rng(11))
    masked = simulate(it, samplers, samplers["A"], np.random.default_rng(11), ignore_mask=np.array([False, True, False]))
    assert np.array_equal(base.completion[:, [0, 2]], masked.completion[:, [0, 2]])        # identical draws for the work that remains
    assert (masked.lock <= base.lock).all()
    sped = simulate(it, samplers, samplers["A"], np.random.default_rng(11), response_override={"A": 2.0}, override_seed=5)
    assert np.array_equal(base.completion[:, 1], sped.completion[:, 1])                      # site B untouched
    assert (sped.lock <= base.lock).all()
