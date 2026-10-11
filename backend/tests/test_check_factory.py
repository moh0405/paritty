import pytest

from app.checks.base import EditCheckSpec
from app.checks.factory import CheckFactory, SpecError


def spec(type_, params):
    return EditCheckSpec(id="t", type=type_, params=params, description="t")


def test_rejects_unknown_table():
    with pytest.raises(SpecError):
        CheckFactory().compile(spec("range", dict(table="pg_catalog.pg_user", column="value", min=1, max=2)))


def test_rejects_unknown_column():
    with pytest.raises(SpecError):
        CheckFactory().compile(spec("range", dict(table="edc.vitals", column="value; DROP TABLE edc.ae", min=1, max=2)))


def test_rejects_unallowed_schema_even_with_valid_column_name():
    with pytest.raises(SpecError):
        CheckFactory().compile(spec("duplicate", dict(table="answer_key.planted", key_cols=["id"])))


def test_range_needs_a_bound():
    with pytest.raises(SpecError):
        CheckFactory().compile(spec("range", dict(table="edc.vitals", column="value")))


def test_values_are_bound_not_interpolated():
    sql, params = CheckFactory().compile(spec("range", dict(table="edc.vitals", column="value", test_code="X'; --", min=1, max=2))).build(None)
    assert "X'; --" not in sql and params["tc"] == "X'; --"


def test_unimplemented_type_is_reported():
    with pytest.raises(SpecError):
        CheckFactory().compile(spec("external_lab", dict(kind="value_mismatch")))
