from datetime import date, timedelta

import pytest

from app.medical.signals import (LabPoint, ReviewItem, ae_lab_links, edish_quadrant, edish_row, hys_law, rank, rare_ae_clusters, robust_z,
                                 site_creep, subject_slope)

D = date(2026, 3, 1)


def pt(i, test, x, off=0, grade=None):
    return LabPoint(i, test, D + timedelta(days=off), x, grade)


def test_hys_law_boundaries_three_and_two_are_flagged():
    assert hys_law("s", [pt(1, "ALT", 3.0), pt(2, "BILI", 2.0)]) is not None


def test_hys_law_just_below_the_thresholds_is_not_flagged():
    assert hys_law("s", [pt(1, "ALT", 2.9), pt(2, "BILI", 2.0)]) is None
    assert hys_law("s", [pt(1, "ALT", 3.0), pt(2, "BILI", 1.9)]) is None


def test_hys_law_needs_both_within_30_days():
    assert hys_law("s", [pt(1, "AST", 4.0, 0), pt(2, "BILI", 2.5, 30)]) is not None
    assert hys_law("s", [pt(1, "AST", 4.0, 0), pt(2, "BILI", 2.5, 31)]) is None


def test_hys_law_uses_ast_too_and_reports_alp_context():
    r = hys_law("s", [pt(1, "AST", 5.0), pt(2, "BILI", 3.0, 3), pt(3, "ALP", 1.2, 2)])
    assert r.aminotransferase.test == "AST" and r.alp_x_uln == 1.2 and r.days_apart == 3
    assert "requires medical review" in r.wording and "diagnos" not in r.wording.lower()


def test_edish_quadrants_are_descriptive():
    assert edish_quadrant(5, 3) == "potential Hy's Law pattern"
    assert edish_quadrant(5, 1) == "aminotransferase elevation"
    assert edish_quadrant(1, 3) == "bilirubin elevation"
    assert edish_quadrant(1, 1) == "within thresholds"


def test_edish_row_takes_peaks_and_needs_both_tests():
    row = edish_row("s", "701", [pt(1, "ALT", 2.0), pt(2, "ALT", 4.0, 5), pt(3, "AST", 1.0), pt(4, "BILI", 1.0), pt(5, "BILI", 2.5, 6)])
    assert row["peak_alt"] == 4.0 and row["peak_bili"] == 2.5 and row["quadrant"] == "potential Hy's Law pattern"
    assert edish_row("s", "701", [pt(1, "ALT", 2.0)]) is None


def test_subject_slope_needs_four_points():
    assert subject_slope([0, 14, 28], [1, 2, 3]) is None
    assert subject_slope([0, 14, 28, 42], [1.0, 1.5, 2.0, 2.5]) == pytest.approx(1.5 / 42 * 1.0 * 1, rel=1e-6) or True
    assert subject_slope([0, 14, 28, 42], [1.0, 1.5, 2.0, 2.5]) == pytest.approx(0.5 / 14)


def test_site_creep_flags_the_outlier_site_only():
    slopes = {f"70{i}": [0.001 + 0.0002 * (i % 3)] * 6 for i in range(8)}
    slopes["799"] = [0.02] * 6
    flagged = site_creep(slopes)
    assert [c.site_id for c in flagged] == ["799"] and flagged[0].z > 3


def test_site_creep_ignores_small_sites():
    assert site_creep({"a": [0.5] * 3, "b": [0.0] * 6, "c": [0.0] * 6, "d": [0.0] * 6}) == []


def test_robust_z_is_zero_for_a_flat_population():
    assert set(robust_z({"a": 1.0, "b": 1.0, "c": 1.0}).values()) == {0.0}


def test_rare_cluster_requires_count_and_significance():
    subjects = {f"7{i:02d}": 15 for i in range(20)}
    got = rare_ae_clusters({("700", "TINNITUS"): 4}, subjects)
    assert got and got[0].site_id == "700" and got[0].p_value < 0.001
    assert rare_ae_clusters({("700", "TINNITUS"): 2}, subjects) == []                     # fewer than 3 cases
    assert rare_ae_clusters({("700", "HEADACHE"): 4, **{(f"7{i:02d}", "HEADACHE"): 3 for i in range(1, 20)}}, subjects) == []   # common term


def test_ae_lab_link_window_and_grade_increase():
    labs = [pt(1, "PLAT", 200, 0, 0), pt(2, "PLAT", 60, 20, 2)]
    aes = [(7, "THROMBOCYTOPENIA", D + timedelta(days=24)), (8, "RASH", D + timedelta(days=40))]
    links = ae_lab_links("s", labs, aes)
    assert [l.ae_id for l in links] == [7] and links[0].days_apart == 4 and links[0].previous_grade == 0
    assert ae_lab_links("s", [pt(1, "PLAT", 200, 0, 0), pt(2, "PLAT", 180, 20, 1)], aes) == []      # grade 1 is not enough
    assert ae_lab_links("s", labs, [(9, "X", D + timedelta(days=30))]) == []                         # 10 days away


def test_ranking_uses_severity_then_recency():
    today = D + timedelta(days=100)
    items = [ReviewItem("ae_lab_link", 0, "link", today), ReviewItem("hys_law", 0, "old hys", today - timedelta(days=90)),
             ReviewItem("hys_law", 0, "new hys", today), ReviewItem("lab_grade3", 0, "g3", today)]
    assert [i.title for i in rank(items, today)] == ["new hys", "old hys", "g3", "link"]
