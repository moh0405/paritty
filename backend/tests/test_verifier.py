"""Verifier cases from spec §16, run against a real seeded row."""
import pytest

from app.domain.enums import Role
from app.llm.schemas import Citation, Claim
from app.verification.checks import VerifyContext
from app.verification.verifier import Verifier


@pytest.fixture
def row(db):
    r = db.execute("SELECT id, usubjid, value, measured_at::date::text FROM edc.vitals WHERE value IS NOT NULL AND test_code = 'SYSBP' ORDER BY id LIMIT 1").fetchone()
    return dict(pk=str(r[0]), usubjid=r[1], value=r[2], day=r[3])


def ctx(db, row, role=Role.DATA_MANAGER, extra=()):
    return VerifyContext(db, role, evidence={("edc.vitals", row["pk"]), *extra})


def cite(row, column="value", value=None, quote=None, pk=None, table="edc.vitals"):
    return Citation(table=table, pk=pk or row["pk"], column=column, value=str(row["value"] if value is None and column == "value" else value), quote=quote)


def run(db, row, claims, **kw):
    return Verifier().verify(claims, ctx(db, row, **kw))


def test_correct_claim_passes(db, row):
    res = run(db, row, [Claim(text=f"The recorded value is {row['value']:g}.", citations=[cite(row)])])
    assert res.status == "verified" and res.grounding_rate == 1.0


def test_wrong_value_is_blocked(db, row):
    res = run(db, row, [Claim(text="The recorded value is 999.", citations=[cite(row, value="999")])])
    assert res.status == "blocked" and res.claims[0].status == "contradicted"
    assert any(c.name == "ValueMatches" and not c.passed for c in res.claims[0].checks)


def test_invented_number_is_blocked(db, row):
    res = run(db, row, [Claim(text=f"The value {row['value']:g} was recorded 987654 times.", citations=[cite(row)])])
    assert res.status == "blocked"
    assert any(c.name == "ClaimNumbersCovered" and not c.passed and "987654" in c.detail for c in res.claims[0].checks)


def test_fabricated_quote_is_blocked(db, row):
    res = run(db, row, [Claim(text="The subject id is quoted.", citations=[cite(row, column="usubjid", value=row["usubjid"], quote="NOT-IN-SOURCE")])])
    assert res.status == "blocked" and res.claims[0].status == "contradicted"


def test_real_quote_passes(db, row):
    res = run(db, row, [Claim(text="The subject is identified.", citations=[cite(row, column="usubjid", value=row["usubjid"], quote=row["usubjid"][:6])])])
    assert res.status == "verified"


def test_out_of_role_citation_is_blocked(db, row):
    res = run(db, row, [Claim(text=f"The recorded value is {row['value']:g}.", citations=[cite(row)])], role=Role.STUDY_LEAD)
    assert res.status == "blocked"
    assert any(c.name == "RoleVisible" and not c.passed for c in res.claims[0].checks)


def test_citation_outside_handed_evidence_is_rejected(db, row):
    v = VerifyContext(db, Role.DATA_MANAGER, evidence=set())
    res = Verifier().verify([Claim(text=f"Value {row['value']:g}.", citations=[cite(row)])], v)
    assert res.status == "blocked" and any(c.name == "EvidenceSubset" and not c.passed for c in res.claims[0].checks)


def test_missing_row_and_forbidden_table_fail(db, row):
    res = run(db, row, [Claim(text="x", citations=[cite(row, pk="999999999")])], extra=[("edc.vitals", "999999999")])
    assert any(c.name == "RowExists" and not c.passed for c in res.claims[0].checks)
    res = run(db, row, [Claim(text="x", citations=[Citation(table="answer_key.planted", pk="1", column="kind", value="x")])],
              extra=[("answer_key.planted", "1")])
    assert res.status == "blocked" and any("may not be cited" in c.detail for c in res.claims[0].checks)


def test_claim_without_citations_is_blocked(db, row):
    assert run(db, row, [Claim(text="Something happened.", citations=[])]).status == "blocked"


def test_date_in_claim_must_match_cited_cell(db, row):
    ok = run(db, row, [Claim(text=f"Measured on {row['day']}.", citations=[cite(row, column="measured_at", value=row["day"])])])
    assert ok.status == "verified"
    bad = run(db, row, [Claim(text="Measured on 1999-01-01.", citations=[cite(row, column="measured_at", value=row["day"])])])
    assert bad.status == "blocked"


def test_rule_thresholds_and_ratios_are_allowed(db, row):
    v = VerifyContext(db, Role.DATA_MANAGER, evidence={("edc.vitals", row["pk"])}, rule_numbers={60.0, 250.0})
    res = Verifier().verify([Claim(text=f"{row['value']:g} against a range of 60-250.", citations=[cite(row)])], v)
    assert res.status == "verified"
    ratio = round(row["value"] / 60, 2)   # derived ratio of a cited cell and a rule number is not a cited ratio -> needs two cited cells
    res = Verifier().verify([Claim(text=f"The ratio is {ratio:g}.", citations=[cite(row)])], v)
    assert res.status == "blocked"


def test_two_cited_cells_allow_a_ratio(db, row):
    r2 = db.execute("SELECT id, value FROM edc.vitals WHERE test_code = 'DIABP' AND value IS NOT NULL LIMIT 1").fetchone()
    ratio = row["value"] / r2[1]
    v = VerifyContext(db, Role.DATA_MANAGER, evidence={("edc.vitals", row["pk"]), ("edc.vitals", str(r2[0]))})
    res = Verifier().verify([Claim(text=f"The ratio of systolic to diastolic is {ratio:.2f}.",
                                   citations=[cite(row), Citation(table="edc.vitals", pk=str(r2[0]), column="value", value=str(r2[1]))])], v)
    assert res.status == "verified"


def test_partial_when_some_claims_verify_and_none_contradict(db, row):
    res = run(db, row, [Claim(text=f"The recorded value is {row['value']:g}.", citations=[cite(row)]),
                        Claim(text="It happened 424242 times.", citations=[cite(row)])])
    assert res.status == "partial" and res.grounding_rate == 0.5


def test_contradiction_beats_partial(db, row):
    res = run(db, row, [Claim(text=f"The recorded value is {row['value']:g}.", citations=[cite(row)]),
                        Claim(text="Wrong.", citations=[cite(row, value="12345")])])
    assert res.status == "blocked"


def test_null_cell_can_be_cited_as_null_or_missing(db):
    r = db.execute("SELECT id FROM edc.ae WHERE severity IS NOT NULL LIMIT 1").fetchone()
    db.execute("UPDATE edc.ae SET severity = NULL WHERE id = %s", (r[0],))
    pk = str(r[0])
    for word in ("null", "None", "missing", ""):
        res = Verifier().verify([Claim(text="The severity is missing.", citations=[Citation(table="edc.ae", pk=pk, column="severity", value=word)])],
                                VerifyContext(db, Role.DATA_MANAGER, evidence={("edc.ae", pk)}))
        assert res.status == "verified", word
    bad = Verifier().verify([Claim(text="The severity is mild.", citations=[Citation(table="edc.ae", pk=pk, column="severity", value="MILD")])],
                            VerifyContext(db, Role.DATA_MANAGER, evidence={("edc.ae", pk)}))
    assert bad.status == "blocked"


def test_dates_computed_by_the_rule_are_allowed_but_model_dates_are_not(db, row):
    claim = Claim(text=f"Recorded {row['value']:g}; expected within 7 days of 2026-03-07.", citations=[cite(row)])
    allowed = VerifyContext(db, Role.DATA_MANAGER, evidence={("edc.vitals", row["pk"])}, rule_dates={"2026-03-07"}, rule_numbers={7.0})
    assert Verifier().verify([claim], allowed).status == "verified"
    assert Verifier().verify([claim], ctx(db, row)).status == "blocked"
