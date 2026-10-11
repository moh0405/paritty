import psycopg
import pytest

from app.db.connection import scoped_connection
from app.domain.enums import Role


def test_medical_monitor_cannot_read_unblinded():
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with scoped_connection(Role.MEDICAL_MONITOR) as conn:
            conn.execute("SELECT * FROM unblinded.randomization")


def test_study_lead_cannot_read_patient_level_ae():
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with scoped_connection(Role.STUDY_LEAD) as conn:
            conn.execute("SELECT * FROM edc.ae")


def test_study_lead_can_read_site_summary():
    with scoped_connection(Role.STUDY_LEAD) as conn:
        conn.execute("SELECT * FROM hub.v_site_summary").fetchall()


def test_unblinded_statistician_can_read_randomization():
    with scoped_connection(Role.UNBLINDED_STATISTICIAN) as conn:
        conn.execute("SELECT * FROM unblinded.randomization").fetchall()


def test_no_app_role_reads_answer_key():
    for role in Role:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with scoped_connection(role) as conn:
                conn.execute("SELECT * FROM answer_key.planted")


def test_site_scope_rls_filters_rows():
    with scoped_connection(Role.DATA_MANAGER, "nonexistent-site") as conn:
        assert conn.execute("SELECT count(*) FROM edc.subjects").fetchone()[0] == 0
