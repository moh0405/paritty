from datetime import date, timedelta

import pytest

from app.recon.labs import (EdcLab, LabReconciler, VendorLab, compare, is_stale, match_subject, parse_vendor_date, to_edc_units)
from app.recon.refs import usubjid_from_lab_ref

D = date(2026, 3, 10)


def e(i=1, test="ALT", value=30.0, unit="U/L", day=D):
    return EdcLab(i, "01-701-1001", "701", test, value, unit, day)


def v(i=1, test="ALT", value=30.0, unit="U/L", day=D, usubjid="01-701-1001"):
    return VendorLab(i, usubjid, test, value, unit, day, day)


def test_reference_and_date_parsing():
    assert usubjid_from_lab_ref("PT701-1015") == "01-701-1015" and usubjid_from_lab_ref("junk") is None
    assert parse_vendor_date("09/03/2026") == date(2026, 3, 9) and parse_vendor_date("2026-03-09") is None


def test_matching_is_one_to_one_within_one_day_and_prefers_exact_dates():
    pairs, e_only, v_only = match_subject([e(1, day=D), e(2, day=D + timedelta(days=1))], [v(10, day=D + timedelta(days=1))])
    assert [(a.id, b.id) for a, b in pairs] == [(2, 10)] and [x.id for x in e_only] == [1] and not v_only
    pairs, e_only, v_only = match_subject([e(1)], [v(10, day=D + timedelta(days=2))])
    assert not pairs and len(e_only) == 1 and len(v_only) == 1                 # two days apart: not the same sample
    pairs, *_ = match_subject([e(1, test="ALT")], [v(10, test="AST")])
    assert not pairs                                                           # different test


def test_value_tolerance_is_one_percent_of_the_edc_value():
    assert compare(e(value=100.0), v(value=100.9)) is None
    d = compare(e(value=100.0), v(value=101.5))
    assert d and d.kind == "value" and "1%" not in d.detail
    assert compare(e(value=0.0), v(value=0.0)) is None


def test_bilirubin_umol_is_converted_to_mg_dl_before_comparing():
    assert to_edc_units("BILI", 17.1, "umol/L", "mg/dL") == (1.0, "mg/dL")
    assert compare(e(test="BILI", value=1.0, unit="mg/dL"), v(test="BILI", value=17.1, unit="umol/L")) is None
    assert compare(e(test="BILI", value=1.0, unit="mg/dL"), v(test="BILI", value=25.0, unit="umol/L")).kind == "value"


def test_unit_difference_is_reported_as_a_unit_mismatch_not_a_value_mismatch():
    d = compare(e(unit="U/L"), v(unit="g/L"))
    assert d.kind == "unit" and "units differ" in d.detail
    assert compare(e(unit=None), v(unit=None)) is None                          # both missing: consistent


def test_stale_feed_needs_recent_collection_and_more_than_three_quiet_days():
    assert is_stale(D - timedelta(days=4), D, True) and not is_stale(D - timedelta(days=3), D, True)
    assert not is_stale(D - timedelta(days=10), D, False)                       # nothing being collected: a quiet feed is fine
    assert is_stale(None, D, True)


def test_reconciler_flags_each_difference_and_resolves_when_the_feed_is_corrected(db):
    from tests.test_library_checks import subject
    day = date(2026, 6, 1)
    db.execute("UPDATE ops.sim_clock SET today = %s", (day,))
    db.execute("DELETE FROM lab_vendor.transfer"); db.execute("DELETE FROM edc.lab")
    subject(db, "01-701-9999")
    db.execute("INSERT INTO edc.subjects (usubjid, site_id, age, sex, consent_at, first_dose_at, status, is_synthetic, entered_at) VALUES ('01-701-9998','701',70,'F','2026-01-01','2026-01-01','enrolled',true,'2026-01-01') ON CONFLICT DO NOTHING")
    when = date(2026, 5, 1)
    for i, (test, val, unit) in enumerate([("ALT", 30, "U/L"), ("AST", 25, "U/L"), ("ALP", 80, "U/L"), ("CREAT", 70, "umol/L")]):
        db.execute("INSERT INTO edc.lab (usubjid, site_id, test_code, value, unit, uln, lln, visit, collected_at, entered_at) VALUES ('01-701-9999','701',%s,%s,%s,40,5,'V',%s,%s)", (test, val, unit, when, when))
    names = dict(db.execute("SELECT test_code, test_name FROM hub.lab_test_map"))
    def vendor(test, result, unit, off=0):
        db.execute("INSERT INTO lab_vendor.transfer (file_date, accession_no, patient_ref, test_name, result, unit, collected, released) VALUES (%s,%s,'PT701-9999',%s,%s,%s,%s,true)",
                   (when, f"X-{test}", names[test], result, unit, (when + timedelta(days=off)).strftime("%d/%m/%Y")))
    vendor("ALT", "30", "U/L"); vendor("AST", "40", "U/L"); vendor("ALP", "80", "g/L")           # ALP: unit mismatch, AST: value mismatch, CREAT: no vendor record
    db.execute("INSERT INTO lab_vendor.transfer (file_date, accession_no, patient_ref, test_name, result, unit, collected, released) VALUES (%s,'LATE','PT701-9998',%s,'1','U/L','01/05/2026',true)", (day - timedelta(days=1), names["ALT"]))   # the feed has moved on
    rec = LabReconciler(db)
    out = rec.run(day, full=True)
    got = {c for (c,) in db.execute("SELECT check_id FROM ops.check_failures WHERE usubjid = '01-701-9999' AND resolved_on IS NULL")}
    assert got == {"chk_24", "chk_25", "chk_26"} and out["edc_only"] == 1
    db.execute("UPDATE lab_vendor.transfer SET result = '25' WHERE accession_no = 'X-AST'")
    rec.run(day + timedelta(days=1), full=True)
    open_now = {c for (c,) in db.execute("SELECT check_id FROM ops.check_failures WHERE usubjid = '01-701-9999' AND resolved_on IS NULL")}
    assert "chk_24" not in open_now and {"chk_25", "chk_26"} <= open_now


def test_edc_only_waits_for_the_feed_to_reach_the_collection_date(db):
    from tests.test_library_checks import subject
    day = date(2026, 6, 1)
    db.execute("UPDATE ops.sim_clock SET today = %s", (day,))
    db.execute("DELETE FROM lab_vendor.transfer"); db.execute("DELETE FROM edc.lab")
    subject(db, "01-701-9997")
    collected = date(2026, 5, 10)
    db.execute("INSERT INTO edc.lab (usubjid, site_id, test_code, value, unit, uln, lln, visit, collected_at, entered_at) VALUES ('01-701-9997','701','ALT',30,'U/L',40,5,'V',%s,%s)", (collected, collected))
    name = db.execute("SELECT test_name FROM hub.lab_test_map WHERE test_code = 'ALT'").fetchone()[0]
    # the latest file is from before the collection date + grace: the feed is late, so the EDC result is not yet 'missing'
    db.execute("INSERT INTO lab_vendor.transfer (file_date, accession_no, patient_ref, test_name, result, unit, collected, released) VALUES (%s,'Y1','PT701-9997',%s,'1','U/L','01/04/2026',true)", (collected + timedelta(days=2), name))
    assert LabReconciler(db).compute(day).edc_only == []
    db.execute("INSERT INTO lab_vendor.transfer (file_date, accession_no, patient_ref, test_name, result, unit, collected, released) VALUES (%s,'Y2','PT701-9990',%s,'1','U/L','01/04/2026',true)", (collected + timedelta(days=9), name))
    assert [x.id for x in LabReconciler(db).compute(day).edc_only]                     # the feed has moved past, and the result is still missing


def test_lab_recon_api_shape_and_roles():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/api/recon/labs", headers={"X-Role": "central_monitor"})
    assert r.status_code == 200 and {"feed", "open_by_type", "items"} <= set(r.json())
    assert c.get("/api/recon/labs", headers={"X-Role": "study_lead"}).status_code == 403


def test_a_missing_unit_is_worded_and_never_printed_as_none():
    d = compare(e(value=68.0, unit="U/L"), v(value=35.0, unit=None))
    assert d.kind == "unit" and d.edc_value == "68 U/L" and d.vendor_value == "35 (no unit)"
    assert "None" not in f"{d.edc_value} {d.vendor_value} {d.detail}"
