"""Build verified, rule-based findings (spec §11: rule flags carry {rule, threshold, comparison_group, value, source_rows}
and render in the same evidence panel). Claim text is formatted from the cited cells, so it always matches them."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from psycopg import Connection

from app.domain.enums import Role
from app.llm.schemas import Citation, Claim
from app.verification.checks import VerifyContext
from app.verification.sources import fetch_row
from app.verification.store import save_finding
from app.verification.verifier import Verifier


@dataclass
class ClaimSpec:
    table: str
    pk: str
    columns: list[str]
    fmt: str          # e.g. "{test_code} was {x_uln:.2f}x ULN on {collected_at:.10}."


def _text(v) -> str:
    if v is None:
        return ""
    return f"{v:g}" if isinstance(v, float) else str(v)


class _Fmt(dict):
    pass


def build_claim(conn: Connection, spec: ClaimSpec) -> Claim | None:
    row = fetch_row(conn, spec.table, spec.pk)
    if row is None:
        return None
    text = spec.fmt.format(**{k: ("" if v is None else v) for k, v in row.items()})
    return Claim(text=text, citations=[Citation(table=spec.table, pk=spec.pk, column=c, value=_text(row.get(c))) for c in spec.columns])


def rule_finding(conn: Connection, *, module: str, rule_id: str, severity: str, usubjid: str | None, site_id: str | None, title: str,
                 claims: list[ClaimSpec], rule: dict, day: date, key: str, rule_numbers: set[float], viewer: Role = Role.MEDICAL_MONITOR) -> str | None:
    """Create (once per `key`) a finding whose claims are verified against the database. Returns the finding id."""
    existing = conn.execute("SELECT id FROM ai.findings WHERE module = %s AND body->>'key' = %s ORDER BY created_at LIMIT 1", (module, key)).fetchone()
    if existing:
        return str(existing[0])
    built = [c for c in (build_claim(conn, s) for s in claims) if c is not None]
    if not built:
        return None
    ctx = VerifyContext(conn, viewer, evidence={(s.table, s.pk) for s in claims}, rule_numbers=rule_numbers)
    result = Verifier().verify(built, ctx)
    return save_finding(conn, module=module, rule_id=rule_id, severity=severity, usubjid=usubjid, site_id=site_id, title=title,
                        claims=built, result=result, sim_date=day, body_extra={"key": key, "rule": rule, "source": "rule"})
