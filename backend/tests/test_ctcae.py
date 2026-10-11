from app.medical.ctcae import grade_lab


def test_alt_grades_on_uln_multiples():
    assert grade_lab("ALT", 30, 34) == 0
    assert grade_lab("ALT", 40, 34) == 1
    assert grade_lab("ALT", 3.5 * 34, 34) == 2
    assert grade_lab("ALT", 6 * 34, 34) == 3
    assert grade_lab("ALT", 25 * 34, 34) == 4


def test_missing_inputs_are_ungraded():
    assert grade_lab("ALT", None, 34) is None
    assert grade_lab("ALT", 40, None) is None
    assert grade_lab("SODIUM", 140, 145) is None


def test_hemoglobin_mmol_converted():
    assert grade_lab("HGB", 4.5, 9.8, 7.4, "mmol/L") == 3   # ~7.2 g/dL
    assert grade_lab("HGB", 8.5, 9.8, 7.4, "mmol/L") == 0
