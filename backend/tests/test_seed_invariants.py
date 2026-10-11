"""Invariants of the seeded golden database (needs `make seed`; skipped otherwise)."""
import json

import pytest

from app.seed.common import PROTOCOL, connect


@pytest.fixture(scope="module")
def conn():
    c = connect()
    try:
        if not c.execute("SELECT count(*) FROM ops.sim_clock").fetchone()[0]:
            pytest.skip("database not seeded")
    except Exception:
        pytest.skip("database not reachable")
    yield c
    c.close()


def one(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_no_child_row_precedes_its_subject(conn):
    for t in ("ae", "lab", "vitals", "visits", "exposure", "conmeds"):
        assert one(conn, f"SELECT count(*) FROM edc.{t} x WHERE NOT EXISTS (SELECT 1 FROM edc.subjects s WHERE s.usubjid = x.usubjid)") == 0, t


def test_nothing_released_is_in_the_future(conn):
    today = one(conn, "SELECT today FROM ops.sim_clock")
    for t in ("subjects", "ae", "lab", "vitals", "visits"):
        assert one(conn, f"SELECT count(*) FROM edc.{t} WHERE entered_at > '{today}'") == 0, t


def test_treatment_arm_only_in_unblinded_schema(conn):
    cols = conn.execute("SELECT table_schema, column_name FROM information_schema.columns "
                        "WHERE column_name ILIKE '%arm%' AND table_schema NOT IN ('information_schema','pg_catalog')").fetchall()
    assert {s for s, _ in cols} <= {"unblinded"}, cols


def test_exposure_dose_is_blinded(conn):
    assert one(conn, "SELECT count(DISTINCT dose) FROM (SELECT dose FROM edc.exposure UNION ALL SELECT dose FROM edc_pending.exposure) x") == 1


def test_at_least_40_serious_cases_with_causality_reference(conn):
    assert one(conn, "SELECT count(DISTINCT safetyreportid) FROM safety.case_versions") >= 40
    assert one(conn, "SELECT count(*) FROM answer_key.causality_reference") >= 40


def test_twenty_four_sites_with_two_per_personality(conn):
    assert one(conn, "SELECT count(*) FROM edc.sites") == 24
    rows = dict(conn.execute("SELECT personality, count(*) FROM answer_key.site_personality GROUP BY 1").fetchall())
    assert rows.pop("normal") == 14 and set(rows.values()) == {2}


def test_planted_baseline_matches_spec_counts(conn):
    k = dict(conn.execute("SELECT module, count(*) FROM answer_key.planted WHERE scenario_run_id IS NULL GROUP BY 1").fetchall())
    assert k["checks"] >= 140 and k["sae_recon"] >= 28 and k["lab_recon"] >= 25
    assert one(conn, "SELECT count(*) FROM answer_key.planted WHERE kind='hys_law_plant' AND scenario_run_id IS NULL") == 3


def test_every_expected_quote_is_in_the_protocol(conn):
    md = (PROTOCOL / "protocol.md").read_text()
    for (quote,) in conn.execute("SELECT expected_quote FROM answer_key.eligibility_qa WHERE expected_quote <> ''").fetchall():
        assert quote in md


def test_vendor_rows_use_aliased_identifiers_and_ddmmyyyy(conn):
    ref, collected = conn.execute("SELECT patient_ref, collected FROM lab_vendor.transfer LIMIT 1").fetchone()
    assert ref.startswith("PT") and len(collected.split("/")) == 3
    assert json.loads(json.dumps(conn.execute("SELECT payload FROM safety.case_versions LIMIT 1").fetchone()[0]))["safetyreportid"]
