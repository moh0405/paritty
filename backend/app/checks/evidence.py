"""Evidence for a failed edit check: the failing row, its subject, nearby rows, and the rule that fired (spec §11)."""
from __future__ import annotations

from dataclasses import dataclass, field

from psycopg import Connection

from app.llm.schemas import Citation, Claim
from app.verification.normalize import extract_dates, extract_numbers
from app.verification.sources import fetch_row

DEFAULT_COL = {"edc.vitals": "value", "edc.lab": "value", "edc.ae": "onset_at", "edc.visits": "actual_date", "edc.exposure": "start_at"}
CHECK_COL = {"chk_09": "end_at", "chk_14": "end_at", "chk_15": "severity", "chk_16": "unit", "chk_20": "term_coded",
             "chk_23": "x_uln", "chk_10": "onset_at", "chk_21": "start_at"}
LABEL = {"value": "value", "onset_at": "onset date", "end_at": "end date", "actual_date": "visit date", "start_at": "start date",
         "severity": "severity", "unit": "unit", "term_coded": "adverse event term", "x_uln": "multiple of ULN",
         "collected_at": "collection date", "measured_at": "measurement date"}
DATE_COL = {"edc.ae": "onset_at", "edc.visits": "actual_date", "edc.lab": "collected_at", "edc.vitals": "measured_at"}


@dataclass
class Evidence:
    rows: list[dict] = field(default_factory=list)            # [{table, pk, row}]
    rule: dict = field(default_factory=dict)                   # {rule, description, expected, observed, severity, ctq}
    rule_numbers: set[float] = field(default_factory=set)
    rule_dates: set[str] = field(default_factory=set)
    cite: tuple[str, str, str] | None = None                   # (table, pk, column) the failure is about

    def keys(self) -> set[tuple[str, str]]:
        return {(r["table"], r["pk"]) for r in self.rows}


def _add(ev: Evidence, conn: Connection, table: str, pk: str) -> dict | None:
    if (table, pk) in ev.keys():
        return next(r["row"] for r in ev.rows if (r["table"], r["pk"]) == (table, pk))
    row = fetch_row(conn, table, pk)
    if row is not None:
        ev.rows.append({"table": table, "pk": pk, "row": row})
    return row


def build(conn: Connection, failure: dict, spec: dict) -> Evidence:
    """failure: check_id, usubjid, src_table, src_pk, observed, expected; spec: description, severity, ctq_category."""
    ev = Evidence(rule={"rule": failure["check_id"], "description": spec["description"], "expected": failure["expected"],
                        "observed": failure["observed"], "severity": spec["severity"], "ctq": spec["ctq_category"]})
    for text in (spec["description"], failure["expected"] or "", failure["src_pk"]):
        ev.rule_numbers.update(extract_numbers(text.replace("|", " ")))
        ev.rule_dates.update(extract_dates(text))
    table, pk, u = failure["src_table"], failure["src_pk"], failure["usubjid"]
    if "|" in pk:                                  # missing visit: no row exists, so cite the baseline visit
        base = conn.execute("SELECT id FROM edc.visits WHERE usubjid = %s AND visit = 'BASELINE' ORDER BY id LIMIT 1", (u,)).fetchone()
        if base:
            _add(ev, conn, "edc.visits", str(base[0]))
            ev.cite = ("edc.visits", str(base[0]), "actual_date")
    else:
        col = CHECK_COL.get(failure["check_id"]) or (DATE_COL.get(table) if failure["check_id"] in ("chk_12", "chk_13") else None) or DEFAULT_COL.get(table)
        row = _add(ev, conn, table, pk)
        if row is not None and col:
            ev.cite = (table, pk, col)
    if u:
        _add(ev, conn, "edc.subjects", u)
        sib = {"edc.vitals": ("test_code", "measured_at"), "edc.lab": ("test_code", "collected_at")}.get(table)
        if sib and ev.cite:
            code = fetch_row(conn, table, pk)["test_code"]
            ids = conn.execute(f"SELECT id FROM {table} WHERE usubjid = %s AND test_code = %s AND id <> %s ORDER BY {sib[1]} DESC LIMIT 5",
                               (u, code, int(pk))).fetchall()
            for (i,) in ids:
                _add(ev, conn, table, str(i))
        elif table in ("edc.ae", "edc.visits", "edc.exposure") and "|" not in pk:
            for (i,) in conn.execute(f"SELECT id FROM {table} WHERE usubjid = %s AND id <> %s ORDER BY id DESC LIMIT 4", (u, int(pk))).fetchall():
                _add(ev, conn, table, str(i))
    return ev


def _cell_text(v) -> str:
    if v is None:
        return "missing"
    if isinstance(v, float):
        return f"{round(v, 2):g}"
    return str(v)[:10] if isinstance(v, str) and len(v) > 10 and v[4] == "-" and v[7] == "-" else str(v)


def template_claims(ev: Evidence) -> list[Claim]:
    """Deterministic, always-verifiable claims about the failing cell."""
    if not ev.cite:
        return []
    table, pk, col = ev.cite
    row = next(r["row"] for r in ev.rows if (r["table"], r["pk"]) == (table, pk))
    raw = row.get(col)
    value = "" if raw is None else (f"{raw:g}" if isinstance(raw, float) else str(raw))
    label = LABEL.get(col, col)
    text = f"The recorded {label} is {_cell_text(raw)}." if "|" not in ev.rule.get("observed", "") else f"The {label} of the baseline visit is {_cell_text(raw)}."
    return [Claim(text=text, citations=[Citation(table=table, pk=pk, column=col, value=value)])]
