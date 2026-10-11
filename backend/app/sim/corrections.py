"""How a simulated site 'fixes' a failed check (spec §9.1 SiteResponder). Corrections are heuristics over the
visible data only (e.g. the subject's median) - the simulator never consults the planted truth.
Each fixer returns True if it changed data; `wrong=True` produces a correction that still fails the check."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Callable

import numpy as np
from psycopg import Connection

from app.medical.ctcae import GRADED_TESTS, grade_lab
from app.sim.ingestor import ChangeSet
from app.sim import lab_desk, safety_desk
from app.sim.schedule import SCHEDULE

Fix = Callable[[Connection, dict, ChangeSet, date, bool, np.random.Generator], bool]

EXPLAIN_ONLY = {"chk_12", "chk_18", "chk_23"}   # facts that cannot be edited: the site explains, the DM closes with explanation
RANGE_CHECKS = {"chk_01", "chk_02", "chk_03", "chk_04", "chk_05", "chk_06", "chk_07", "chk_08"}


def _vital_value(conn, f, cs, day, wrong, r) -> bool:
    row = conn.execute("SELECT usubjid, test_code, value, site_id FROM edc.vitals WHERE id = %s", (int(f["src_pk"]),)).fetchone()
    if row is None:
        return False
    usubjid, test, value, site = row
    if wrong:
        new = round(value * 0.97, 1)
    else:
        new = conn.execute("SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY value) FROM edc.vitals "
                           "WHERE usubjid = %s AND test_code = %s AND id <> %s AND value IS NOT NULL", (usubjid, test, int(f["src_pk"]))).fetchone()[0]
        if new is None:
            new = conn.execute("SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY value) FROM edc.vitals "
                               "WHERE site_id = %s AND test_code = %s AND id <> %s", (site, test, int(f["src_pk"]))).fetchone()[0]
        if new is None:
            return False
        new = round(float(new), 1)
    conn.execute("UPDATE edc.vitals SET value = %s WHERE id = %s", (new, int(f["src_pk"])))
    cs.mark_updated("vitals", int(f["src_pk"]))
    return True


def _ae_update(conn, ae_id: int, sets: str, params: tuple, cs: ChangeSet) -> bool:
    conn.execute(f"UPDATE edc.ae SET {sets}, updated_at = now() WHERE id = %s", (*params, ae_id))
    cs.mark_updated("ae", ae_id)
    return True


def _ae_end_before_start(conn, f, cs, day, wrong, r) -> bool:
    ae_id = int(f["src_pk"])
    if wrong:
        return _ae_update(conn, ae_id, "end_at = end_at - 1", (), cs)
    return _ae_update(conn, ae_id, "end_at = onset_at + 5", (), cs)


def _ae_before_consent(conn, f, cs, day, wrong, r) -> bool:
    ae_id = int(f["src_pk"])
    if wrong:
        return _ae_update(conn, ae_id, "onset_at = onset_at - 1", (), cs)
    return _ae_update(conn, ae_id, "onset_at = (SELECT consent_at FROM edc.subjects s WHERE s.usubjid = edc.ae.usubjid)", (), cs)


def _visit_order(conn, f, cs, day, wrong, r) -> bool:
    vid = int(f["src_pk"])
    if wrong:
        conn.execute("UPDATE edc.visits SET actual_date = actual_date - 1 WHERE id = %s", (vid,))
    else:
        conn.execute("UPDATE edc.visits v SET actual_date = b.actual_date + v.planned_day - 1 FROM edc.visits b "
                     "WHERE v.id = %s AND b.usubjid = v.usubjid AND b.visit = 'BASELINE'", (vid,))
    cs.mark_updated("visits", vid)
    return True


def _future_date(conn, f, cs, day, wrong, r) -> bool:
    table = f["src_table"].split(".")[1]
    rid = int(f["src_pk"])
    col = {"ae": "onset_at", "visits": "actual_date", "lab": "collected_at", "vitals": "measured_at"}[table]
    if wrong:
        conn.execute(f"UPDATE edc.{table} SET {col} = {col} + interval '1 day' WHERE id = %s", (rid,))
    else:
        conn.execute(f"UPDATE edc.{table} SET {col} = entered_at WHERE id = %s", (rid,))
    cs.mark_updated(table, rid)
    return True


def _exposure_end(conn, f, cs, day, wrong, r) -> bool:
    rid = int(f["src_pk"])
    conn.execute("UPDATE edc.exposure SET end_at = " + ("end_at - 1" if wrong else "start_at + 1") + " WHERE id = %s", (rid,))
    cs.mark_updated("exposure", rid)
    return True


def _fill_ae_required(conn, f, cs, day, wrong, r) -> bool:
    if wrong:
        return False
    return _ae_update(conn, int(f["src_pk"]),
                      "severity = COALESCE(severity, 'MODERATE'), outcome = COALESCE(outcome, 'NOT RECOVERED/NOT RESOLVED')", (), cs)


def _fill_lab_required(conn, f, cs, day, wrong, r) -> bool:
    if wrong:
        return False
    rid = int(f["src_pk"])
    usubjid, test, value, unit, uln, lln = conn.execute(
        "SELECT usubjid, test_code, value, unit, uln, lln FROM edc.lab WHERE id = %s", (rid,)).fetchone()
    mode = lambda col: conn.execute(f"SELECT mode() WITHIN GROUP (ORDER BY {col}) FROM edc.lab WHERE test_code = %s AND {col} IS NOT NULL", (test,)).fetchone()[0]  # noqa: E731
    unit = unit if unit is not None else mode("unit")
    uln = uln if uln is not None else mode("uln")
    lln = lln if lln is not None else mode("lln")
    x = value / uln if (value is not None and uln) else None
    grade = grade_lab(test, value, uln, lln, unit) if test in GRADED_TESTS else None
    conn.execute("UPDATE edc.lab SET unit = %s, uln = %s, lln = %s, x_uln = %s, ctcae_grade = %s WHERE id = %s",
                 (unit, uln, lln, x, grade, rid))
    cs.mark_updated("lab", rid)
    return True


def _enter_missing_visit(conn, f, cs, day, wrong, r) -> bool:
    if wrong:
        return False
    usubjid, visit = f["src_pk"].split("|")
    planned = dict(SCHEDULE)[visit]
    base = conn.execute("SELECT site_id, actual_date FROM edc.visits WHERE usubjid = %s AND visit = 'BASELINE' LIMIT 1", (usubjid,)).fetchone()
    if base is None:
        return False
    rid = conn.execute(
        "INSERT INTO edc.visits (usubjid, site_id, visit, planned_day, actual_date, entered_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (usubjid, base[0], visit, planned, base[1] + timedelta(days=planned - 1 + int(r.integers(0, 4))), day)).fetchone()[0]
    cs.mark_inserted("visits", rid)
    return True


def _delete_row(conn, f, cs, day, wrong, r) -> bool:
    if wrong:
        return False
    table = f["src_table"].split(".")[1]
    conn.execute(f"DELETE FROM edc.{table} WHERE id = %s", (int(f["src_pk"]),))
    return True


_CASE_REF = re.compile(r"v_cases#(\d+)")


def _case_id(conn, failure: dict) -> str | None:
    if failure["src_table"] == "safety.case_versions":
        return failure["src_pk"]
    m = _CASE_REF.search(failure.get("expected") or "")
    row = conn.execute("SELECT safetyreportid FROM safety.case_versions WHERE id = %s", (int(m.group(1)),)).fetchone() if m else None
    return row[0] if row else None


def _sae_followup(field: str) -> Fix:
    """Site confirms its EDC value; the safety desk issues a follow-up version that agrees with it."""
    def fix(conn, f, cs, day, wrong, r) -> bool:
        if wrong:
            return False
        case_id = _case_id(conn, f)
        ae = conn.execute("SELECT term_coded, onset_at, serious, causality, outcome FROM edc.ae WHERE id = %s", (int(f["src_pk"]),)).fetchone()
        if not case_id or ae is None:
            return False
        return safety_desk.issue_followup(conn, case_id, dict(zip(("term_coded", "onset_at", "serious", "causality", "outcome"), ae)), field, day)
    return fix


def _sae_one_sided(conn, f, cs, day, wrong, r) -> bool:
    """EDC-only: the safety desk opens the case. Safety-only: the site enters the missing AE in EDC."""
    if wrong:
        return False
    if f["src_table"] == "edc.ae":
        return safety_desk.open_case(conn, int(f["src_pk"]), day)
    case = conn.execute("SELECT reaction_term, onset, causality, outcome, subject_ref FROM safety.v_cases WHERE safetyreportid = %s "
                        "ORDER BY version DESC LIMIT 1", (f["src_pk"],)).fetchone()
    if case is None or not f["usubjid"]:
        return False
    term, onset, causality, outcome, _ref = case
    from app.recon.sae.classifier import E2B_OUTCOME_LABEL
    caus = {"Related": "PROBABLE", "Not related": "REMOTE"}.get(causality)
    rid = conn.execute(
        "INSERT INTO edc.ae (usubjid, site_id, source_seq, term_verbatim, term_coded, onset_at, serious, severity, causality, outcome, entered_at) "
        "VALUES (%s,%s,800,%s,%s,%s,true,'SEVERE',%s,%s,%s) RETURNING id",
        (f["usubjid"], f["usubjid"].split("-")[1], term, term, onset, caus, E2B_OUTCOME_LABEL.get(outcome or ""), day)).fetchone()[0]
    cs.mark_inserted("ae", rid)
    return True


_VENDOR_REF = re.compile(r"transfer#(\d+)")


def _lab_fix(conn, f, cs, day, wrong, r) -> bool:
    """chk_24/26: the lab re-issues the record; chk_25: whichever side lacks the result gets it."""
    if wrong:
        return False
    if f["check_id_hint"] in ("chk_24", "chk_26"):
        m = _VENDOR_REF.search(f.get("expected") or "")
        return bool(m) and lab_desk.correct_vendor(conn, int(m.group(1)), int(f["src_pk"]))
    if f["src_table"] == "edc.lab":
        return lab_desk.reissue_missing(conn, int(f["src_pk"]), day)
    new = lab_desk.enter_missing_in_edc(conn, int(f["src_pk"]), day)
    if new:
        cs.mark_inserted("lab", new)
    return bool(new)


FIXERS: dict[str, Fix] = {
    "chk_24": _lab_fix, "chk_25": _lab_fix, "chk_26": _lab_fix,
    **{f"sae_{k}": _sae_followup(k) for k in ("onset", "term", "seriousness", "causality", "outcome", "death")},
    "chk_22": _sae_one_sided, "sae_safety_only": _sae_one_sided, "sae_fatal_one_sided": _sae_one_sided,
    **{c: _vital_value for c in RANGE_CHECKS},
    "chk_09": _ae_end_before_start, "chk_10": _ae_before_consent, "chk_11": _visit_order, "chk_13": _future_date,
    "chk_14": _exposure_end, "chk_15": _fill_ae_required, "chk_16": _fill_lab_required, "chk_17": _enter_missing_visit,
    "chk_19a": _delete_row, "chk_19b": _delete_row, "chk_20": _delete_row, "chk_21": _delete_row,
}
