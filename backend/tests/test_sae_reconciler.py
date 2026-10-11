"""SaeReconciler end to end on fixture rows: failures appear, queries can be drafted, and a follow-up version resolves them."""
import json
from datetime import date, timedelta

from app.recon.sae.reconciler import SaeReconciler
from app.sim import safety_desk
from tests.test_library_checks import BAD, subject

TODAY = date(2026, 6, 1)


def setup_case(db, *, onset_shift=0, term="SYNCOPE", case_term=None, outcome="RECOVERED/RESOLVED", case_outcome="1", entered=TODAY - timedelta(days=20)):
    db.execute("UPDATE ops.sim_clock SET today = %s", (TODAY,))
    subject(db, BAD)
    onset = TODAY - timedelta(days=30)
    ae_id = db.execute("INSERT INTO edc.ae (usubjid, site_id, source_seq, term_verbatim, term_coded, onset_at, serious, severity, causality, outcome, entered_at) "
                       "VALUES (%s,'701',1,%s,%s,%s,true,'SEVERE','PROBABLE',%s,%s) RETURNING id", (BAD, term, term, onset, outcome, entered)).fetchone()[0]
    payload = {"safetyreportid": "LSTEST1", "receivedate": "20260502", "serious": "1", "seriousnessother": "1",
               "patient": {"reaction": [{"reactionmeddrapt": case_term or term, "reactionstartdate": (onset + timedelta(days=onset_shift)).strftime("%Y%m%d"),
                                         "reactionoutcome": case_outcome}]}}
    db.execute("INSERT INTO safety.case_versions (safetyreportid, version, receivedate, subject_ref, payload, causality, narrative, available_on) "
               "VALUES ('LSTEST1',1,'20260502','SUBJ BAD / SITE 701',%s,'Related','n',%s)", (json.dumps(payload), TODAY - timedelta(days=15)))
    # the test subject id is not numeric; point the case at it the way the feed does
    db.execute("UPDATE safety.case_versions SET subject_ref = 'SUBJ 9999 / SITE 701' WHERE safetyreportid = 'LSTEST1'")
    db.execute("UPDATE edc.ae SET usubjid = '01-701-9999' WHERE id = %s", (ae_id,))
    db.execute("INSERT INTO edc.subjects (usubjid, site_id, age, sex, consent_at, first_dose_at, status, is_synthetic, entered_at) "
               "VALUES ('01-701-9999','701',70,'F','2026-01-01','2026-01-01','enrolled',true,'2026-01-01')")
    return ae_id


def failures(db, usubjid="01-701-9999"):
    return {(c, r) for c, r in db.execute("SELECT check_id, resolved_on IS NOT NULL FROM ops.check_failures WHERE usubjid = %s "
                                          "AND (check_id LIKE 'sae\\_%%' OR check_id = 'chk_22')", (usubjid,))}


def test_agreeing_case_raises_nothing(db):
    setup_case(db)
    SaeReconciler(db).run(TODAY, allow_llm=False)
    assert failures(db) == set()


def test_acceptable_differences_raise_nothing(db):
    setup_case(db, onset_shift=1, case_term="FAINTING")
    SaeReconciler(db).run(TODAY, allow_llm=False)
    assert failures(db) == set()


def test_onset_difference_over_one_day_raises_a_failure_with_case_reference(db):
    setup_case(db, onset_shift=4)
    SaeReconciler(db).run(TODAY, allow_llm=False)
    assert failures(db) == {("sae_onset", False)}
    expected = db.execute("SELECT expected FROM ops.check_failures WHERE check_id = 'sae_onset' AND usubjid = '01-701-9999'").fetchone()[0]
    assert "v_cases#" in expected


def test_unreported_ae_is_edc_only_after_the_grace_period(db):
    ae_id = setup_case(db, entered=TODAY - timedelta(days=10))
    db.execute("DELETE FROM safety.case_versions WHERE safetyreportid = 'LSTEST1'")
    SaeReconciler(db).run(TODAY, allow_llm=False)
    assert failures(db) == {("chk_22", False)}
    db.execute("UPDATE edc.ae SET entered_at = %s WHERE id = %s", (TODAY - timedelta(days=1), ae_id))      # now inside the 3-day window
    SaeReconciler(db).run(TODAY + timedelta(days=1), allow_llm=False)
    assert failures(db) == {("chk_22", True)}                                                             # no longer a discrepancy


def test_follow_up_version_resolves_the_failure(db):
    ae_id = setup_case(db, onset_shift=4)
    rec = SaeReconciler(db)
    rec.run(TODAY, allow_llm=False)
    ae = dict(zip(("term_coded", "onset_at", "serious", "causality", "outcome"),
                  db.execute("SELECT term_coded, onset_at, serious, causality, outcome FROM edc.ae WHERE id = %s", (ae_id,)).fetchone()))
    assert safety_desk.issue_followup(db, "LSTEST1", ae, "onset", TODAY)
    out = rec.run(TODAY, allow_llm=False)
    assert failures(db) == {("sae_onset", True)} and out["open_discrepancies"] >= 0
    pair = [p for p in rec.compute(TODAY).pairs if p.match.ae.id == ae_id][0]
    assert pair.match.case.version == 2 and pair.overall == "acceptable"   # follow-up detail is acceptable, not a discrepancy


def test_death_mismatch_is_critical(db):
    setup_case(db, case_outcome="5")
    SaeReconciler(db).run(TODAY, allow_llm=False)
    assert ("sae_death", False) in failures(db)


def test_safety_case_without_edc_ae_is_flagged_and_history_is_written(db):
    ae_id = setup_case(db)
    db.execute("DELETE FROM edc.ae WHERE id = %s", (ae_id,))
    out = SaeReconciler(db).run(TODAY, allow_llm=False)
    assert ("sae_safety_only", False) in failures(db) and out["safety_only"] >= 1
    assert db.execute("SELECT counts->>'safety_only' FROM ops.sae_recon_history WHERE sim_date = %s", (TODAY,)).fetchone()[0] is not None


def test_issue_followup_is_idempotent_for_open_case(db):
    ae_id = setup_case(db)
    db.execute("DELETE FROM safety.case_versions WHERE safetyreportid = 'LSTEST1'")
    assert safety_desk.open_case(db, ae_id, TODAY)
    assert not safety_desk.open_case(db, ae_id, TODAY)     # second attempt is a no-op instead of a duplicate-key error
