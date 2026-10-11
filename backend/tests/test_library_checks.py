"""Each library check flags a fixture error and passes a clean row (spec §16). Rows go in a rolled-back transaction."""
from datetime import date, timedelta

import pytest

from app.checks.factory import CheckFactory
from app.checks.library import LIBRARY
from app.sim.schedule import SCHEDULE

D0 = date(2026, 1, 1)
BAD, OK = "TEST-BAD", "TEST-OK"


def subject(c, u, consent=D0, status="enrolled", death=None, disc=None):
    c.execute("INSERT INTO edc.subjects (usubjid, site_id, age, sex, consent_at, first_dose_at, discontinued_at, death_at, status, is_synthetic, entered_at) "
              "VALUES (%s,'701',70,'F',%s,%s,%s,%s,%s,true,%s)", (u, consent, consent, disc, death, status, consent))


def vital(c, u, test, value, day=D0, minute=0):
    c.execute("INSERT INTO edc.vitals (usubjid, site_id, test_code, value, unit, visit, measured_at, entered_at) "
              "VALUES (%s,'701',%s,%s,'u','V',%s::timestamptz + (%s || ' minutes')::interval,%s)", (u, test, value, day, minute, day))


def lab(c, u, test="ALT", value=20.0, unit="U/L", uln=34.0, x=None, day=D0):
    c.execute("INSERT INTO edc.lab (usubjid, site_id, test_code, value, unit, uln, lln, x_uln, visit, collected_at, entered_at) "
              "VALUES (%s,'701',%s,%s,%s,%s,5,%s,'V',%s,%s)", (u, test, value, unit, uln, x, day, day))


def ae(c, u, term="HEADACHE", onset=D0 + timedelta(days=10), end=None, serious=False, severity="MILD", outcome="RECOVERED/RESOLVED", seq=1):
    c.execute("INSERT INTO edc.ae (usubjid, site_id, source_seq, term_verbatim, term_coded, onset_at, end_at, serious, severity, outcome, entered_at) "
              "VALUES (%s,'701',%s,%s,%s,%s,%s,%s,%s,%s,%s)", (u, seq, term, term, onset, end, serious, severity, outcome, onset))


def visit(c, u, name, planned, day):
    c.execute("INSERT INTO edc.visits (usubjid, site_id, visit, planned_day, actual_date, entered_at) VALUES (%s,'701',%s,%s,%s,%s)", (u, name, planned, day, day))


def exposure(c, u, start, end):
    c.execute("INSERT INTO edc.exposure (usubjid, site_id, dose, start_at, end_at, entered_at) VALUES (%s,'701',1,%s,%s,%s)", (u, start, end, start))


def range_case(test, bad, ok):
    def setup(c):
        subject(c, BAD), subject(c, OK)
        vital(c, BAD, test, bad), vital(c, OK, test, ok)
    return setup


def all_visits(c, u):
    visit(c, u, "BASELINE", 1, D0)
    for name, pd_ in SCHEDULE:
        visit(c, u, name, pd_, D0 + timedelta(days=pd_ - 1))


def c07(c):
    subject(c, BAD), subject(c, OK)
    for i, v in enumerate([70, 70, 154]):
        vital(c, BAD, "WEEK" if False else "WEIGHT", v, minute=i)
    for i, v in enumerate([70, 71, 72]):
        vital(c, OK, "WEIGHT", v, minute=i)


def c09(c):
    subject(c, BAD), subject(c, OK)
    ae(c, BAD, onset=D0 + timedelta(days=10), end=D0 + timedelta(days=5))
    ae(c, OK, onset=D0 + timedelta(days=10), end=D0 + timedelta(days=15))


def c10(c):
    subject(c, BAD, consent=D0 + timedelta(days=30)), subject(c, OK, consent=D0)
    ae(c, BAD, onset=D0 + timedelta(days=10))
    ae(c, OK, onset=D0 + timedelta(days=10))


def c11(c):
    subject(c, BAD), subject(c, OK)
    for u, wk2 in ((BAD, D0 - timedelta(days=5)), (OK, D0 + timedelta(days=13))):
        visit(c, u, "BASELINE", 1, D0)
        visit(c, u, "WEEK 2", 14, wk2)


def c12(c):
    subject(c, BAD, death=D0 + timedelta(days=5)), subject(c, OK, death=D0 + timedelta(days=50))
    visit(c, BAD, "WEEK 2", 14, D0 + timedelta(days=14))
    visit(c, OK, "WEEK 2", 14, D0 + timedelta(days=14))


def c13(c):
    c.execute("UPDATE ops.sim_clock SET today = '2026-03-06'")
    subject(c, BAD), subject(c, OK)
    ae(c, BAD, onset=date(2026, 4, 1))
    ae(c, OK, onset=date(2026, 3, 1))


def c14(c):
    subject(c, BAD), subject(c, OK)
    exposure(c, BAD, D0 + timedelta(days=10), D0 + timedelta(days=2))
    exposure(c, OK, D0 + timedelta(days=10), D0 + timedelta(days=20))


def c15(c):
    subject(c, BAD), subject(c, OK)
    ae(c, BAD, serious=True, severity=None)
    ae(c, OK, serious=True, severity="SEVERE")


def c16(c):
    subject(c, BAD), subject(c, OK)
    lab(c, BAD, unit=None)
    lab(c, OK)


def c17(c):
    c.execute("UPDATE ops.sim_clock SET today = '2030-01-01'")
    subject(c, BAD), subject(c, OK)
    visit(c, BAD, "BASELINE", 1, D0)           # nothing after baseline, long overdue, subject still enrolled
    all_visits(c, OK)


def c18(c):
    subject(c, BAD), subject(c, OK)
    for u, wk4 in ((BAD, D0 + timedelta(days=45)), (OK, D0 + timedelta(days=28))):
        visit(c, u, "BASELINE", 1, D0)
        visit(c, u, "WEEK 4", 28, wk4)


def c19a(c):
    subject(c, BAD), subject(c, OK)
    lab(c, BAD), lab(c, BAD)
    lab(c, OK), lab(c, OK, day=D0 + timedelta(days=1))


def c19b(c):
    subject(c, BAD), subject(c, OK)
    vital(c, BAD, "PULSE", 70), vital(c, BAD, "PULSE", 70)
    vital(c, OK, "PULSE", 70), vital(c, OK, "PULSE", 70, minute=2)


def c20(c):
    subject(c, BAD), subject(c, OK)
    ae(c, BAD), ae(c, BAD)
    ae(c, OK, seq=1), ae(c, OK, seq=2)


def c21(c):
    subject(c, BAD, disc=D0 + timedelta(days=20), status="discontinued"), subject(c, OK, disc=D0 + timedelta(days=60), status="discontinued")
    exposure(c, BAD, D0 + timedelta(days=30), D0 + timedelta(days=40))
    exposure(c, OK, D0 + timedelta(days=30), D0 + timedelta(days=40))


def c23(c):
    subject(c, BAD), subject(c, OK)
    lab(c, BAD, value=170, x=5.0), lab(c, OK, value=170, x=5.0)
    ae(c, OK, term="HEPATIC ENZYME INCREASED", onset=D0 + timedelta(days=3))


CASES = {
    "chk_01": range_case("SYSBP", 300, 120), "chk_02": range_case("DIABP", 200, 80), "chk_03": range_case("PULSE", 250, 70),
    "chk_04": range_case("TEMP", 29, 36.6), "chk_05": range_case("WEIGHT", 5, 70), "chk_06": range_case("HEIGHT", 60, 170),
    "chk_07": c07, "chk_08": range_case("TEMP", 98.4, 37.0), "chk_09": c09, "chk_10": c10, "chk_11": c11, "chk_12": c12,
    "chk_13": c13, "chk_14": c14, "chk_15": c15, "chk_16": c16, "chk_17": c17, "chk_18": c18, "chk_19a": c19a, "chk_19b": c19b,
    "chk_20": c20, "chk_21": c21, "chk_23": c23,
}


def test_every_active_library_check_has_a_fixture():
    assert {s.id for s in LIBRARY if s.active} == set(CASES)


def test_library_has_26_checks_and_four_are_deferred():
    assert len({s.id.rstrip("ab") for s in LIBRARY}) == 26 - 0 and sum(not s.active for s in LIBRARY) == 4


@pytest.mark.parametrize("check_id", sorted(CASES))
def test_check_flags_bad_row_and_passes_clean_row(db, check_id):
    CASES[check_id](db)
    spec = next(s for s in LIBRARY if s.id == check_id)
    failed = {f.usubjid for f in CheckFactory().compile(spec).run(db)}
    assert BAD in failed, f"{check_id} did not flag the bad fixture"
    assert OK not in failed, f"{check_id} flagged the clean fixture"
