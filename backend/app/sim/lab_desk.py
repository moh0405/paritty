"""The simulated central lab: when a site confirms its EDC result, the lab re-issues the record; a result only the lab holds is entered by the site.
Part of the simulator, not of any detector."""
from __future__ import annotations

from datetime import date, datetime, time

from psycopg import Connection

from app.medical.ctcae import GRADED_TESTS, grade_lab
from app.recon.labs import BILI_UMOL_PER_MGDL


def _vendor_fields(test: str, value: float | None, unit: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, unit
    if test == "BILI" and (unit or "").lower() == "mg/dl":
        return str(round(value * BILI_UMOL_PER_MGDL, 2)), "umol/L"
    return str(value), unit


def correct_vendor(conn: Connection, vendor_id: int, edc_lab_id: int) -> bool:
    row = conn.execute("SELECT test_code, value, unit FROM edc.lab WHERE id = %s", (edc_lab_id,)).fetchone()
    if row is None:
        return False
    result, unit = _vendor_fields(*row)
    conn.execute("UPDATE lab_vendor.transfer SET result = %s, unit = %s WHERE id = %s", (result, unit, vendor_id))
    return True


def reissue_missing(conn: Connection, edc_lab_id: int, day: date) -> bool:
    """EDC has a result the central lab file lacks: the lab sends it (effective today)."""
    r = conn.execute("SELECT l.usubjid, l.test_code, l.value, l.unit, l.collected_at::date, m.test_name FROM edc.lab l JOIN hub.lab_test_map m ON m.test_code = l.test_code WHERE l.id = %s", (edc_lab_id,)).fetchone()
    if r is None:
        return False
    usubjid, test, value, unit, collected, name = r
    if conn.execute("SELECT 1 FROM lab_vendor.transfer WHERE accession_no = %s", (f"ACC-{edc_lab_id:07d}",)).fetchone():
        return False
    result, v_unit = _vendor_fields(test, value, unit)
    _, site, num = usubjid.split("-")
    conn.execute("INSERT INTO lab_vendor.transfer (file_date, accession_no, patient_ref, test_name, result, unit, collected, released) VALUES (%s,%s,%s,%s,%s,%s,%s,true)",
                 (day, f"ACC-{edc_lab_id:07d}", f"PT{site}-{num}", name, result, v_unit, collected.strftime("%d/%m/%Y")))
    return True


def enter_missing_in_edc(conn: Connection, vendor_id: int, day: date) -> int | None:
    """The central lab has a result the EDC lacks: the site enters it. Returns the new EDC lab id."""
    r = conn.execute("SELECT t.patient_ref, m.test_code, t.result, t.unit, t.collected FROM lab_vendor.transfer t JOIN hub.lab_test_map m ON lower(m.test_name) = lower(t.test_name) WHERE t.id = %s", (vendor_id,)).fetchone()
    if r is None:
        return None
    ref, test, result, unit, collected = r
    num, site = ref.split("-")[1], ref[2:].split("-")[0]
    usubjid = f"01-{site}-{num}"
    value = float(result)
    if test == "BILI" and (unit or "").lower() in ("umol/l", "µmol/l"):
        value, unit = value / BILI_UMOL_PER_MGDL, "mg/dL"
    ref_row = conn.execute("SELECT uln, lln FROM edc.lab WHERE usubjid = %s AND test_code = %s AND uln IS NOT NULL ORDER BY collected_at DESC LIMIT 1", (usubjid, test)).fetchone() \
        or conn.execute("SELECT mode() WITHIN GROUP (ORDER BY uln), mode() WITHIN GROUP (ORDER BY lln) FROM edc.lab WHERE test_code = %s", (test,)).fetchone()
    uln, lln = ref_row if ref_row else (None, None)
    when = datetime.combine(datetime.strptime(collected, "%d/%m/%Y").date(), time(8))
    return conn.execute(
        "INSERT INTO edc.lab (usubjid, site_id, test_code, value, unit, uln, lln, x_uln, ctcae_grade, visit, collected_at, entered_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s) RETURNING id",
        (usubjid, site, test, round(value, 3), unit, uln, lln, (value / uln) if uln else None,
         grade_lab(test, value, uln, lln, unit) if test in GRADED_TESTS else None, when, day)).fetchone()[0]
