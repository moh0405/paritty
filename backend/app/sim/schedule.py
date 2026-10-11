"""Protocol visit schedule (synthetic protocol §5; modeled on the pilot TV domain)."""
from app.sim.constants import VISIT_WINDOW_DAYS

CLINIC_VISITS: list[tuple[str, int]] = [
    ("WEEK 2", 14), ("WEEK 4", 28), ("WEEK 6", 42), ("WEEK 8", 56), ("WEEK 12", 84),
    ("WEEK 16", 112), ("WEEK 20", 140), ("WEEK 24", 168), ("WEEK 26", 182),
]
# Telephone contacts are scheduled visits too (protocol §5: "Visits at Week 10, 14, 18 and 22 are telephone contacts").
PHONE_VISITS: list[tuple[str, int]] = [("WEEK 10 (T)", 70), ("WEEK 14 (T)", 98), ("WEEK 18 (T)", 126), ("WEEK 22 (T)", 154)]
SCHEDULE: list[tuple[str, int]] = sorted(CLINIC_VISITS + PHONE_VISITS, key=lambda v: v[1])
ENTRY_GRACE_DAYS = 5   # protocol: CRF data entered within 5 days of the visit
WINDOW = VISIT_WINDOW_DAYS
