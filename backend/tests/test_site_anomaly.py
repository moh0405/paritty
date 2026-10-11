import numpy as np
import pytest

from app.sites.anomaly import borderline_share, duplicate_panels, terminal_digit_test, timing_ks, underreporting, variance_ratio
from app.sites.risk import rule_scores

rng = np.random.default_rng(0)


def test_uniform_digits_are_not_flagged_but_rounded_digits_are():
    uniform = list(rng.integers(100, 200, 500))
    chi, p, counts = terminal_digit_test(uniform)
    assert p > 0.001 and sum(counts) == 500
    rounded = [int(round(v, -1)) for v in uniform]
    _, p2, c2 = terminal_digit_test(rounded)
    assert p2 < 1e-10 and c2[0] == 500


def test_terminal_digit_needs_enough_readings():
    assert terminal_digit_test([120, 130, 140]) is None


def test_variance_ratio_flags_regular_readings():
    study = [8.0] * 40
    assert variance_ratio([2.0] * 6, study) == pytest.approx(0.25)
    assert variance_ratio([8.0] * 6, study) == pytest.approx(1.0)
    assert variance_ratio([2.0] * 3, study) is None                      # too few subjects


def test_duplicate_panels_counts_subjects_sharing_a_panel():
    panel = tuple(("SYSBP", v) for v in (120, 121, 122)) + tuple(("DIABP", v) for v in (80, 81, 82))
    other = tuple(("SYSBP", v) for v in (130, 131, 132)) + tuple(("DIABP", v) for v in (70, 71, 72))
    got = duplicate_panels({("a", "W4"): panel, ("b", "W4"): panel, ("c", "W4"): panel, ("d", "W4"): other})
    assert got == 3
    assert duplicate_panels({("a", "W4"): panel, ("d", "W4"): other}) == 0


def test_underreporting_is_one_sided_and_needs_exposure():
    expected, p = underreporting(2, 30.0, 0.5)
    assert expected == 15.0 and p < 0.001
    assert underreporting(15, 30.0, 0.5)[1] > 0.4
    assert underreporting(0, 1.0, 0.5) is None


def test_timing_ks_detects_a_shifted_distribution():
    same = timing_ks(list(rng.normal(0, 2, 50)), list(rng.normal(0, 2, 200)))
    shifted = timing_ks(list(rng.normal(9, 4, 50)), list(rng.normal(0, 2, 200)))
    assert same[1] > 0.01 and shifted[1] < 0.001
    assert timing_ks([0.0] * 5, [0.0] * 50) is None


def test_borderline_share_is_a_one_sided_test():
    share, p = borderline_share(8, 12, 0.1)
    assert share == pytest.approx(8 / 12) and p < 0.001
    assert borderline_share(1, 12, 0.1)[1] > 0.3
    assert borderline_share(3, 5, 0.1) is None


def test_rule_score_ranks_the_outlier_site_highest_and_stays_in_range():
    feats = {f"s{i}": {"kri:entry_lag_days": 3.0 + 0.1 * i, "kri:query_rate": 2.0 + 0.05 * i, "anom:terminal_digit": 0.5} for i in range(10)}
    feats["bad"] = {"kri:entry_lag_days": 25.0, "kri:query_rate": 9.0, "anom:terminal_digit": 6.0}
    scores, z = rule_scores(feats)
    assert max(scores, key=scores.get) == "bad" and all(0 <= v <= 100 for v in scores.values())
    assert z["bad"]["kri:entry_lag_days"] == 4.0                          # capped
    assert 40 < scores["s4"] < 60                                         # typical sites sit near the middle


def test_two_sided_kris_treat_low_and_high_as_unusual():
    feats = {f"s{i}": {"kri:ae_rate": 1.0 + 0.02 * i} for i in range(9)}
    feats["low"] = {"kri:ae_rate": 0.1}
    _, z = rule_scores(feats)
    assert z["low"]["kri:ae_rate"] > 3
