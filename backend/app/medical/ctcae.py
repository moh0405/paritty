"""CTCAE grading for the lab tests we model (spec §6).

Thresholds follow CTCAE v5.0 as recalled by the author; they have NOT been confirmed against the
current NCI file (spec §18) - see docs/DECISIONS.md. Liver/renal tests grade on multiples of ULN;
hematology grades on absolute values (hemoglobin g/dL, platelets and neutrophils 10^9/L).
"""
from __future__ import annotations

import math

HGB_MMOL_TO_GDL = 1.611

# (grade1 upper bound exclusive-from, grade2, grade3, grade4) as x ULN lower edges: value > edge -> grade
_ULN_EDGES: dict[str, tuple[float, float, float, float]] = {
    "ALT": (1.0, 3.0, 5.0, 20.0),
    "AST": (1.0, 3.0, 5.0, 20.0),
    "ALP": (1.0, 2.5, 5.0, 20.0),
    "BILI": (1.0, 1.5, 3.0, 10.0),
    "CREAT": (1.0, 1.5, 3.0, 6.0),
}


def _isnum(x: float | None) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def grade_lab(test_code: str, value: float | None, uln: float | None, lln: float | None = None,
              unit: str | None = None) -> int | None:
    """Return CTCAE grade 0-4, or None if the test is not graded / inputs missing."""
    if not _isnum(value):
        return None
    if test_code in _ULN_EDGES:
        if not _isnum(uln) or uln <= 0:
            return None
        x = value / uln
        grade = 0
        for g, edge in enumerate(_ULN_EDGES[test_code], start=1):
            if x > edge:
                grade = g
        return grade
    if test_code == "HGB":
        gdl = value * HGB_MMOL_TO_GDL if (unit or "").lower().startswith("mmol") else value
        lln_gdl = (lln * HGB_MMOL_TO_GDL if (unit or "").lower().startswith("mmol") else lln) if _isnum(lln) else None
        if gdl < 8.0:
            return 3
        if gdl < 10.0:
            return 2
        if lln_gdl is not None and gdl < lln_gdl:
            return 1
        return 0
    if test_code == "PLAT":
        if value < 25:
            return 4
        if value < 50:
            return 3
        if value < 75:
            return 2
        if _isnum(lln) and value < lln:
            return 1
        return 0
    if test_code == "NEUT":
        if value < 0.5:
            return 4
        if value < 1.0:
            return 3
        if value < 1.5:
            return 2
        if _isnum(lln) and value < lln:
            return 1
        return 0
    return None


GRADED_TESTS = set(_ULN_EDGES) | {"HGB", "PLAT", "NEUT"}
