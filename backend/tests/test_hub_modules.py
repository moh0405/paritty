import psycopg
import pytest

from app.domain.enums import Role
from app.db.connection import as_role
from app.hub import catalog, dq, lineage, questions


def test_dq_rules_cover_all_four_dimensions_and_run(db):
    assert {r.dimension for r in dq.RULES} == set(dq.DIMENSIONS)
    day = db.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
    out = dq.run(db, day)
    assert len(out) == len(dq.RULES) and all(isinstance(o["failed_rows"], int) for o in out)
    latest = dq.latest(db)
    assert {x["dimension"] for x in latest} == set(dq.DIMENSIONS)


def test_dq_flags_a_planted_impossible_date(db):
    db.execute("INSERT INTO ctms.monitoring_visits (site_code, visit_date, type) VALUES ('SITE-0701', DATE '1900-01-01', 'On-site')")
    day = db.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
    dq.run(db, day)
    row = [x for x in dq.latest(db) if x["rule"] == "ctms_impossible_dates"][0]
    assert row["failed_rows"] >= 1 and row["sample_pks"]


def test_catalog_refresh_and_search(db):
    day = db.execute("SELECT today FROM ops.sim_clock").fetchone()[0]
    assert catalog.refresh(db, day) > 20
    hits = catalog.search(db, "adverse events", day)
    assert any(h["table_name"] == "edc.ae" for h in hits)
    assert all(h["age_days"] is None or h["age_days"] >= 0 for h in hits)
    assert catalog.search(db, "", day)[0]["table_name"]
    assert any(h["table_name"] == "lab_vendor.transfer" for h in catalog.search(db, "lab_vendor", day))


def test_five_questions_exist_and_have_lineage(db):
    assert [q["id"] for q in questions.catalog()] == [1, 2, 3, 4, 5]
    for n in range(1, 6):
        r = questions.run(db, n)
        assert r["level"] in ("patient-level", "site-level") and "sql" in r["lineage"] and r["lineage"]["tables"]


def test_the_same_question_returns_different_results_per_role(db):
    db.execute("INSERT INTO edc.subjects (usubjid, site_id, age, sex, consent_at, first_dose_at, discontinued_at, status, is_synthetic, entered_at) "
               "VALUES ('01-701-8888','701',70,'F','2026-01-01','2026-01-02','2026-02-01','discontinued',true,'2026-01-01')")
    db.execute("INSERT INTO edc.exposure (usubjid, site_id, dose, start_at, end_at, entered_at) VALUES ('01-701-8888','701',1,'2026-02-10','2026-02-12','2026-02-12')")
    with as_role(db, Role.DATA_MANAGER) as c:
        dm = questions.run(c, 2)
    with as_role(db, Role.STUDY_LEAD) as c:
        lead = questions.run(c, 2)
    assert dm["level"] == "patient-level" and any(r.get("usubjid") == "01-701-8888" for r in dm["rows"])
    assert lead["level"] == "site-level" and "usubjid" not in lead["columns"] and "can't see" in lead["note"]
    assert any(r["site_id"] == "701" for r in lead["rows"])
    with as_role(db, Role.DATA_MANAGER, "702") as c:                       # site scope hides subjects at other sites
        scoped = questions.run(c, 2)
    assert not any(r.get("usubjid") == "01-701-8888" for r in scoped["rows"])


def test_unknown_question_is_a_key_error(db):
    with pytest.raises(KeyError):
        questions.run(db, 9)


def test_lineage_trail_for_a_failure_and_a_query(db):
    fid = db.execute("INSERT INTO ops.check_failures (check_id, usubjid, site_id, src_table, src_pk, observed, expected, detected_on) "
                     "VALUES ('chk_01','01-701-1001','701','edc.vitals','1','300','between 60 and 250','2026-03-06') RETURNING id").fetchone()[0]
    t = lineage.trail(db, "failure", str(fid))
    labels = [s["label"] for s in t["steps"]]
    assert labels == ["Source row", "Rule that fired", "Failure recorded"] and t["steps"][0]["table"] == "edc.vitals"
    assert lineage.trail(db, "query", "00000000-0000-0000-0000-000000000000")["steps"] == []


def test_noise_variants_are_all_recoverable_by_normalization_or_fuzzy_matching():
    from app.evals.injectors.hub import noisy_lab, noisy_safety
    from app.hub.normalize import parse_lab_ref, parse_safety_ref
    for v in range(4):
        n = noisy_lab("PT701-1015", v)
        k = parse_lab_ref(n)
        assert (k.usubjid == "01-701-1015") if v < 3 else k is None        # the missing-separator form is left to the fuzzy matcher
    for v in range(3):
        assert parse_safety_ref(noisy_safety("SUBJ 1015 / SITE 701", v)).usubjid == "01-701-1015"
