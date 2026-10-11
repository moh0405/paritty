"""Evidence for a failed edit check: the failing row, its subject, nearby rows, and the rule that fired (spec §11)."""
from __future__ import annotations

from dataclasses import dataclass, field

from psycopg import Connection

from app.llm.schemas import Citation, Claim
import re

from app.recon.lab_specs import LAB_SPECS
from app.recon.sae.specs import SAE_SPEC_IDS

LAB_SPEC_IDS = {x.id for x in LAB_SPECS}
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
    cites: list[tuple[str, str, str, str]] = field(default_factory=list)   # (table, pk, column, claim prefix) the failure is about

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
    if failure["check_id"] in SAE_SPEC_IDS:
        return _build_sae(conn, failure, ev)
    if failure["check_id"] in LAB_SPEC_IDS:
        return _build_lab(conn, failure, ev)
    if "|" in pk:                                  # missing visit: no row exists, so cite the baseline visit
        base = conn.execute("SELECT id FROM edc.visits WHERE usubjid = %s AND visit = 'BASELINE' ORDER BY id LIMIT 1", (u,)).fetchone()
        if base:
            _add(ev, conn, "edc.visits", str(base[0]))
            ev.cites = [("edc.visits", str(base[0]), "actual_date", "The visit date of the baseline visit")]
    else:
        col = CHECK_COL.get(failure["check_id"]) or (DATE_COL.get(table) if failure["check_id"] in ("chk_12", "chk_13") else None) or DEFAULT_COL.get(table)
        row = _add(ev, conn, table, pk)
        if row is not None and col:
            ev.cites = [(table, pk, col, f"The recorded {LABEL.get(col, col)}")]
    if u:
        _add(ev, conn, "edc.subjects", u)
        sib = {"edc.vitals": ("test_code", "measured_at"), "edc.lab": ("test_code", "collected_at")}.get(table)
        if sib and ev.cites:
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
    """Deterministic, always-verifiable claims about the failing cell(s)."""
    claims = []
    for table, pk, col, prefix in ev.cites:
        row = next(r["row"] for r in ev.rows if (r["table"], r["pk"]) == (table, pk))
        raw = row.get(col)
        value = "" if raw is None else (f"{raw:g}" if isinstance(raw, float) else str(raw))
        claims.append(Claim(text=f"{prefix} is {_cell_text(raw)}.", citations=[Citation(table=table, pk=pk, column=col, value=value)]))
    return claims


# (EDC column, safety view column, label) per SAE discrepancy spec
SAE_COLS = {"sae_onset": ("onset_at", "onset", "onset date"), "sae_term": ("term_coded", "reaction_term", "event term"),
            "sae_seriousness": ("serious", "serious", "seriousness flag"), "sae_causality": ("causality", "causality", "causality"),
            "sae_outcome": ("outcome", "outcome", "outcome"), "sae_death": ("outcome", "death", "death indicator")}
_CASE_REF = re.compile(r"v_cases#(\d+)")


def _case_row(ev: Evidence, conn: Connection, row_id: str) -> None:
    row = fetch_row(conn, "safety.v_cases", row_id)
    if row is not None:
        row = {k: v for k, v in row.items() if k != "narrative"}   # free text is not needed to state the facts
        ev.rows.append({"table": "safety.v_cases", "pk": row_id, "row": row})


def _build_sae(conn: Connection, failure: dict, ev: Evidence) -> Evidence:
    cid, pk, u = failure["check_id"], failure["src_pk"], failure["usubjid"]
    m = _CASE_REF.search(failure["expected"] or "")
    case_row = m.group(1) if m else None
    if failure["src_table"] == "safety.case_versions":       # safety-only: src_pk is the case id
        r = conn.execute("SELECT id FROM safety.v_cases WHERE safetyreportid = %s ORDER BY version DESC LIMIT 1", (pk,)).fetchone()
        case_row = str(r[0]) if r else case_row
    else:
        _add(ev, conn, "edc.ae", pk)
    if case_row:
        _case_row(ev, conn, case_row)
    if u:
        _add(ev, conn, "edc.subjects", u)
    for text in (failure["expected"] or "", failure["observed"] or ""):
        ev.rule_numbers.update(extract_numbers(re.sub(r"v_cases#\d+", "", text)))
        ev.rule_dates.update(extract_dates(text))
    if cid in SAE_COLS and case_row:
        e_col, s_col, label = SAE_COLS[cid]
        ev.cites = [("edc.ae", pk, e_col, f"The EDC {label}"), ("safety.v_cases", case_row, s_col, f"The safety database {label}")]
    elif failure["src_table"] == "edc.ae":
        ev.cites = [("edc.ae", pk, "term_coded", "The EDC event term"), ("edc.ae", pk, "onset_at", "The EDC onset date")]
    elif case_row:
        ev.cites = [("safety.v_cases", case_row, "reaction_term", "The safety database event term"), ("safety.v_cases", case_row, "onset", "The safety database onset date")]
    return ev


_VENDOR_REF = re.compile(r"transfer#(\d+)")


def _build_lab(conn: Connection, failure: dict, ev: Evidence) -> Evidence:
    cid, pk, table, u = failure["check_id"], failure["src_pk"], failure["src_table"], failure["usubjid"]
    m = _VENDOR_REF.search(failure["expected"] or "")
    vendor_id = pk if table == "lab_vendor.transfer" else (m.group(1) if m else None)
    if cid == "lab_stale_feed":
        return ev
    if table == "edc.lab":
        _add(ev, conn, "edc.lab", pk)
    if vendor_id:
        _add(ev, conn, "lab_vendor.transfer", vendor_id)
    if u:
        _add(ev, conn, "edc.subjects", u)
    for text in (failure["expected"] or "", failure["observed"] or ""):
        ev.rule_numbers.update(extract_numbers(re.sub(r"transfer#\d+", "", text)))
        ev.rule_dates.update(extract_dates(text))
    if cid == "chk_24":
        ev.cites = [("edc.lab", pk, "value", "The EDC result"), ("lab_vendor.transfer", vendor_id, "result", "The central lab result")]
    elif cid == "chk_26":
        ev.cites = [("edc.lab", pk, "unit", "The EDC unit"), ("lab_vendor.transfer", vendor_id, "unit", "The central lab unit")]
    elif table == "edc.lab":
        ev.cites = [("edc.lab", pk, "test_code", "The EDC test"), ("edc.lab", pk, "value", "The EDC result")]
    elif vendor_id:
        ev.cites = [("lab_vendor.transfer", vendor_id, "test_name", "The central lab test"), ("lab_vendor.transfer", vendor_id, "result", "The central lab result")]
    return ev
