from app.sites.kris import rag_abs_high, rag_ratio_both, rag_ratio_high, rag_z


def test_two_sided_ratio_bands():
    assert [rag_ratio_both(v, 1.0) for v in (0.4, 0.6, 1.0, 1.4, 1.6, 2.1)] == ["red", "amber", "green", "green", "amber", "red"]
    assert rag_ratio_both(1.0, 0.0) == "na"


def test_high_is_bad_bands():
    assert [rag_ratio_high(v, 1.0) for v in (0.1, 1.4, 1.6, 2.1)] == ["green", "green", "amber", "red"]


def test_absolute_thresholds_for_lag_and_resolution():
    f = rag_abs_high(14, 7)
    assert [f(v, 0) for v in (3, 7, 8, 14, 15)] == ["green", "green", "amber", "amber", "red"]
    g = rag_abs_high(21, 14)
    assert [g(v, 0) for v in (14, 15, 21, 22)] == ["green", "amber", "amber", "red"]


def test_window_violation_thresholds():
    f = rag_abs_high(0.20, 0.10)
    assert [f(v, 0) for v in (0.05, 0.10, 0.15, 0.25)] == ["green", "green", "amber", "red"]


def test_screen_failure_uses_robust_z():
    vals = {f"s{i}": 0.2 + 0.01 * i for i in range(10)}
    vals["out"] = 0.9
    assert rag_z(vals, "out") == "red" and rag_z(vals, "s3") == "green"
