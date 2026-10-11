"""Learned site risk model: trained on simulated sites only, reproducible, and explained per site. No database."""
import numpy as np
import pytest

from app.sim.personalities import Personality
from app.sites import risk_model as rm

SEED, STUDIES = 7, 8


@pytest.fixture(scope="module")
def model():
    return rm.train(SEED, n_studies=STUDIES)


def test_features_match_the_live_kri_and_anomaly_names():
    from app.sites.kris import KRI_DEFS
    assert rm.FEATURES[:len(KRI_DEFS)] == [f"kri:{k}" for k in KRI_DEFS]
    assert {f.split(":")[1] for f in rm.FEATURES if f.startswith("anom:")} == {
        "terminal_digit", "variance_ratio", "duplicate_panels", "ae_underreporting", "visit_timing", "borderline_eligibility"}


def test_simulated_study_is_deterministic_and_labelled():
    a, la = rm.simulate_study(np.random.default_rng(3))
    b, lb = rm.simulate_study(np.random.default_rng(3))
    assert a == b and la == lb and len(la) == rm.SITES_PER_STUDY
    assert Personality.NORMAL in la.values() and any(p is not Personality.NORMAL for p in la.values())
    assert all(-4 <= z <= 4 for site in a.values() for z in site.values())      # the rule score's capped z-scores


def test_each_planted_pattern_moves_its_own_feature():
    r = np.random.default_rng(11)
    expected = {Personality.TOO_PERFECT: "anom:terminal_digit", Personality.SLOPPY_ENTRY: "kri:entry_lag_days",
                Personality.SLOW_RESPONDER: "kri:query_resolution_days", Personality.RULE_BENDER: "kri:visit_window_violations",
                Personality.UNDER_REPORTER: "anom:ae_underreporting"}
    seen: dict = {p: [] for p in expected}
    typical: dict = {f: [] for f in expected.values()}
    for _ in range(12):
        zs, labels = rm.simulate_study(r)
        for site, pers in labels.items():
            for f in typical:
                if pers is Personality.NORMAL and f in zs[site]:
                    typical[f].append(zs[site][f])
            if pers in expected and expected[pers] in zs[site]:
                seen[pers].append(zs[site][expected[pers]])
    for pers, f in expected.items():
        assert np.mean(seen[pers]) > np.mean(typical[f]) + 1.0, pers


def test_training_is_reproducible_with_a_seed(model):
    again = rm.train(SEED, n_studies=STUDIES)
    zs, _ = rm.simulate_study(np.random.default_rng(99))
    X = rm.to_matrix(zs, sorted(zs))
    assert np.allclose(model.binary.predict_proba(X), again.binary.predict_proba(X))
    assert model.metrics == again.metrics and model.n_sites == STUDIES * rm.SITES_PER_STUDY


def test_model_separates_problem_patterns_on_held_out_studies(model):
    assert model.metrics["holdout_auc"] > 0.85
    assert model.metrics["holdout_precision_at_k"] > 0.7
    assert set(model.importance) == set(rm.FEATURES)


def test_scores_are_explained_by_the_features_that_carry_them(model):
    zs = {"quiet": {f: 0.0 for f in rm.FEATURES},
          "late": {**{f: 0.0 for f in rm.FEATURES}, "kri:entry_lag_days": 4.0, "kri:query_rate": 3.0}}
    out = rm.score_sites(zs, model)
    assert out["late"].score > out["quiet"].score + 30 and 0 <= out["quiet"].score <= 100
    lag = next(c for c in out["late"].contributions if c["feature"] == "kri:entry_lag_days")
    assert lag["label"] == "Median data entry lag (days)" and lag["effect"] > 0 and lag["z"] == 4.0
    assert out["quiet"].contributions == []
    assert out["late"].pattern == Personality.SLOPPY_ENTRY.value
    text = " ".join(rm.PATTERN_LABELS.values()).lower()
    assert not any(w in text for w in ("fraud", "misconduct", "fabricat", "sloppy", "bender"))      # neutral wording only


def test_missing_features_and_a_missing_model_are_handled(model, tmp_path):
    assert rm.score_sites({"s": {"kri:ae_rate": 1.0}}, model)["s"].score >= 0      # sparse early data still scores
    assert rm.score_sites({"empty": {}}, model) == {}
    assert rm.load(tmp_path / "absent.joblib") is None


def test_saved_model_round_trips(model, tmp_path):
    path = tmp_path / "m.joblib"
    rm.save(model, path)
    zs, _ = rm.simulate_study(np.random.default_rng(5))
    assert {s: m.score for s, m in rm.score_sites(zs, rm.load(path)).items()} == {s: m.score for s, m in rm.score_sites(zs, model).items()}
