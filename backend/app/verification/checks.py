"""The six per-claim verification checks (spec §11). Each returns a CheckResult; none calls an LLM."""
from __future__ import annotations

from dataclasses import dataclass, field

import psycopg
from psycopg import Connection

from app.db.connection import as_role
from app.domain.enums import Role
from app.llm.schemas import Citation
from app.verification.normalize import cell_text, extract_dates, extract_numbers, norm_cell, norm_ws
from app.verification.sources import CITABLE, fetch_row


NULL_WORDS = {"", "null", "none", "n/a", "na", "missing", "nan", "empty", "blank"}


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    kind: str = "unsupported"   # on failure: 'unsupported' (cannot be established) or 'contradicted' (evidence disagrees)


@dataclass
class VerifyContext:
    conn: Connection                        # privileged read of the cited rows
    role: Role                              # who will see the claim
    site_scope: str | None = None
    evidence: set[tuple[str, str]] = field(default_factory=set)   # (table, pk) handed to the model
    rule_numbers: set[float] = field(default_factory=set)         # thresholds carried by the rule itself
    rule_dates: set[str] = field(default_factory=set)             # dates the system computed for the rule (e.g. 'expected within 7 days of ...')
    _rows: dict = field(default_factory=dict)

    def row(self, table: str, pk: str) -> dict | None:
        key = (table, pk)
        if key not in self._rows:
            try:
                self._rows[key] = fetch_row(self.conn, table, pk)
            except (KeyError, ValueError):
                self._rows[key] = None
        return self._rows[key]


def evidence_subset(c: Citation, ctx: VerifyContext) -> CheckResult:
    ok = (c.table, c.pk) in ctx.evidence
    return CheckResult("EvidenceSubset", ok, "" if ok else f"{c.table}#{c.pk} was not in the evidence given to the model")


def row_exists(c: Citation, ctx: VerifyContext) -> CheckResult:
    if c.table not in CITABLE:
        return CheckResult("RowExists", False, f"table {c.table} may not be cited")
    ok = ctx.row(c.table, c.pk) is not None
    return CheckResult("RowExists", ok, "" if ok else f"no row {c.table}#{c.pk}")


def role_visible(c: Citation, ctx: VerifyContext) -> CheckResult:
    if c.table not in CITABLE:
        return CheckResult("RoleVisible", False, f"table {c.table} may not be cited")
    try:
        with as_role(ctx.conn, ctx.role, ctx.site_scope) as conn:
            seen = fetch_row(conn, c.table, c.pk) is not None
    except psycopg.errors.InsufficientPrivilege:
        return CheckResult("RoleVisible", False, f"role {ctx.role.value} cannot read {c.table}")
    except (KeyError, ValueError):
        return CheckResult("RoleVisible", False, "bad citation")
    return CheckResult("RoleVisible", seen, "" if seen else f"role {ctx.role.value} cannot see {c.table}#{c.pk}")


def value_matches(c: Citation, ctx: VerifyContext) -> CheckResult:
    row = ctx.row(c.table, c.pk)
    if row is None:
        return CheckResult("ValueMatches", False, "row not found")
    if c.column not in row:
        return CheckResult("ValueMatches", False, f"{c.table} has no column {c.column}")
    if row[c.column] is None:   # a genuinely empty cell may be cited as null/none/n/a/missing
        ok = norm_cell(c.value) in NULL_WORDS
    else:
        ok = norm_cell(row[c.column]) == norm_cell(c.value)
    return CheckResult("ValueMatches", ok, "" if ok else f"cited {c.value!r} but {c.table}#{c.pk}.{c.column} is {row[c.column]!r}", kind="contradicted")


def quote_in_source(c: Citation, ctx: VerifyContext) -> CheckResult | None:
    if not c.quote:
        return None
    row = ctx.row(c.table, c.pk)
    cell = cell_text(row.get(c.column)) if row else ""
    ok = norm_ws(c.quote) in norm_ws(cell)
    return CheckResult("QuoteInSource", ok, "" if ok else f"quote {c.quote!r} is not in {c.table}#{c.pk}.{c.column}", kind="contradicted")


def claim_numbers_covered(text: str, citations: list[Citation], ctx: VerifyContext) -> CheckResult:
    """Every number/date in the claim appears in a cited cell (or the rule's own thresholds), or is a ratio of two cited numbers within 1%."""
    cell_numbers: list[float] = []
    cell_dates: set[str] = set()
    for c in citations:
        row = ctx.row(c.table, c.pk)
        if not row or c.column not in row:
            continue
        v = row[c.column]
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            cell_numbers.append(float(v))
        elif v is not None:
            cell_numbers.extend(extract_numbers(str(v)))
            cell_dates.update(extract_dates(str(v)))
    known = cell_numbers + list(ctx.rule_numbers)
    problems = []
    for d in extract_dates(text):
        if d not in cell_dates and d not in ctx.rule_dates:
            problems.append(d)
    for n in extract_numbers(text):
        if any(abs(n - k) <= 0.005 for k in known):
            continue
        if any(b and abs(n - a / b) <= 0.01 * max(abs(n), 1e-9) for a in cell_numbers for b in cell_numbers):
            continue
        problems.append(f"{n:g}")
    return CheckResult("ClaimNumbersCovered", not problems, "" if not problems else f"not found in cited cells: {', '.join(problems)}")
