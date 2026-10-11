"""External (central) lab reconciliation against the EDC (spec §9.4).
Pure matching/comparison first, then LabReconciler which maintains check failures for the affected subjects each day."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from psycopg import Connection

from app.checks.base import Failure
from app.recon.refs import usubjid_from_lab_ref

BILI_UMOL_PER_MGDL = 17.1
VALUE_TOLERANCE = 0.01          # relative
DATE_TOLERANCE_DAYS = 1
STALE_AFTER_DAYS = 3
EDC_ONLY_GRACE_DAYS = 5         # central-lab results normally arrive within a few days of collection
VENDOR_ONLY_GRACE_DAYS = 30     # sites may enter results up to a few weeks late (sloppy entry lags reach 25 days)
SPEC_VALUE, SPEC_ONE_SIDED, SPEC_UNIT, SPEC_STALE = "chk_24", "chk_25", "chk_26", "lab_stale_feed"
LAB_SPEC_IDS = {SPEC_VALUE, SPEC_ONE_SIDED, SPEC_UNIT, SPEC_STALE}


@dataclass
class EdcLab:
    id: int
    usubjid: str
    site_id: str
    test: str
    value: float | None
    unit: str | None
    day: date


@dataclass
class VendorLab:
    id: int
    usubjid: str | None
    test: str | None
    value: float | None
    unit: str | None
    day: date | None
    file_date: date


@dataclass
class LabDiff:
    kind: str                 # value | unit
    edc: EdcLab
    vendor: VendorLab
    edc_value: str
    vendor_value: str
    detail: str


def parse_vendor_date(s: str | None) -> date | None:
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def parse_float(s: str | None) -> float | None:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def same_unit(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def to_edc_units(test: str, value: float | None, unit: str | None, edc_unit: str | None) -> tuple[float | None, str | None]:
    """Bring a vendor result into the EDC's units where we know the conversion (bilirubin umol/L -> mg/dL)."""
    if value is not None and test == "BILI" and (unit or "").lower() in ("umol/l", "µmol/l") and (edc_unit or "").lower() == "mg/dl":
        return value / BILI_UMOL_PER_MGDL, edc_unit
    return value, unit


def compare(e: EdcLab, v: VendorLab) -> LabDiff | None:
    val, unit = to_edc_units(e.test, v.value, v.unit, e.unit)
    if not same_unit(unit, e.unit):
        return LabDiff("unit", e, v, f"{e.value:g} {e.unit}" if e.value is not None else f"{e.unit}", f"{v.value:g} {v.unit}" if v.value is not None else f"{v.unit}",
                       f"units differ ({e.unit or 'none'} in EDC, {v.unit or 'none'} at the central lab)")
    if e.value is None or val is None:
        return None if e.value is None and val is None else LabDiff("value", e, v, str(e.value), str(v.value), "a result is missing on one side")
    denom = max(abs(e.value), 1e-9)
    if abs(e.value - val) / denom > VALUE_TOLERANCE:
        return LabDiff("value", e, v, f"{e.value:g} {e.unit or ''}".strip(), f"{val:g} {unit or ''}".strip(), f"values differ by {abs(e.value - val) / denom:.0%}")
    return None


def match_subject(edc: list[EdcLab], vendor: list[VendorLab]) -> tuple[list[tuple[EdcLab, VendorLab]], list[EdcLab], list[VendorLab]]:
    """Within one subject: pair on test and collection date within +/-1 day, exact dates first, each record used once."""
    pairs: list[tuple[EdcLab, VendorLab]] = []
    used_e: set[int] = set()
    used_v: set[int] = set()
    cands = sorted(((abs((e.day - v.day).days), e.id, v.id, e, v) for e in edc for v in vendor
                    if v.day is not None and v.test == e.test and abs((e.day - v.day).days) <= DATE_TOLERANCE_DAYS), key=lambda x: x[:3])
    for _d, _ei, _vi, e, v in cands:
        if e.id not in used_e and v.id not in used_v:
            pairs.append((e, v))
            used_e.add(e.id)
            used_v.add(v.id)
    return pairs, [e for e in edc if e.id not in used_e], [v for v in vendor if v.id not in used_v]


def is_stale(last_file: date | None, today: date, edc_collected_recently: bool) -> bool:
    """No central-lab file for more than 3 days while sites are still collecting samples."""
    return edc_collected_recently and (last_file is None or (today - last_file).days > STALE_AFTER_DAYS)


@dataclass
class LabResult:
    day: date
    diffs: list[LabDiff] = field(default_factory=list)
    edc_only: list[EdcLab] = field(default_factory=list)
    vendor_only: list[VendorLab] = field(default_factory=list)
    stale: bool = False
    last_file: date | None = None
    matched: int = 0


class LabReconciler:
    def __init__(self, conn: Connection):
        self.conn = conn
        self.codes = {name.lower(): code for code, name in conn.execute("SELECT test_code, test_name FROM hub.lab_test_map")}

    # ---- data -----------------------------------------------------------------------------------------
    def _edc(self, subjects: set[str] | None) -> dict[str, list[EdcLab]]:
        q = "SELECT id, usubjid, site_id, test_code, value, unit, collected_at::date FROM edc.lab"
        rows = self.conn.execute(q + (" WHERE usubjid = ANY(%s)" if subjects is not None else ""), (sorted(subjects),) if subjects is not None else ()).fetchall()
        out: dict[str, list[EdcLab]] = {}
        for r in rows:
            out.setdefault(r[1], []).append(EdcLab(r[0], r[1], r[2], r[3], r[4], r[5], r[6]))
        return out

    def _vendor(self, subjects: set[str] | None, day: date) -> dict[str, list[VendorLab]]:
        rows = self.conn.execute("SELECT id, patient_ref, test_name, result, unit, collected, file_date FROM lab_vendor.transfer WHERE released AND file_date <= %s", (day,)).fetchall()
        out: dict[str, list[VendorLab]] = {}
        for i, ref, name, result, unit, collected, fd in rows:
            u = usubjid_from_lab_ref(ref)
            if u is None or (subjects is not None and u not in subjects):
                continue
            out.setdefault(u, []).append(VendorLab(i, u, self.codes.get((name or "").lower()), parse_float(result), unit, parse_vendor_date(collected), fd))
        return out

    def affected_subjects(self, day: date, lab_ids: set[int]) -> set[str]:
        """Subjects whose central-lab file arrived today or whose EDC lab rows changed today."""
        subj = {u for (r,) in self.conn.execute("SELECT DISTINCT patient_ref FROM lab_vendor.transfer WHERE released AND file_date = %s", (day,)) if (u := usubjid_from_lab_ref(r))}
        if lab_ids:
            subj |= {u for (u,) in self.conn.execute("SELECT DISTINCT usubjid FROM edc.lab WHERE id = ANY(%s)", (sorted(lab_ids),))}
        return subj

    # ---- compute ---------------------------------------------------------------------------------------
    def compute(self, day: date, subjects: set[str] | None = None) -> LabResult:
        res = LabResult(day)
        edc, vendor = self._edc(subjects), self._vendor(subjects, day)
        last = self.conn.execute("SELECT max(file_date) FROM lab_vendor.transfer WHERE released AND file_date <= %s", (day,)).fetchone()[0]
        covered = min(day, last) if last else day - timedelta(days=3650)     # the feed has reached this date: results collected earlier should be in it
        for u in set(edc) | set(vendor):
            pairs, e_only, v_only = match_subject(edc.get(u, []), vendor.get(u, []))
            res.matched += len(pairs)
            res.diffs += [d for e, v in pairs if (d := compare(e, v))]
            res.edc_only += [e for e in e_only if e.day + timedelta(days=EDC_ONLY_GRACE_DAYS) < covered]
            res.vendor_only += [v for v in v_only if v.day and v.day + timedelta(days=VENDOR_ONLY_GRACE_DAYS) < day and v.test]
        recent = self.conn.execute("SELECT EXISTS (SELECT 1 FROM edc.lab WHERE collected_at::date > %s)", (day - timedelta(days=STALE_AFTER_DAYS),)).fetchone()[0]
        res.last_file, res.stale = last, is_stale(last, day, recent)
        return res

    def failures(self, res: LabResult) -> dict[str, list[Failure]]:
        out: dict[str, list[Failure]] = {s: [] for s in LAB_SPEC_IDS}
        for d in res.diffs:
            out[SPEC_UNIT if d.kind == "unit" else SPEC_VALUE].append(Failure(
                src_table="edc.lab", src_pk=str(d.edc.id), usubjid=d.edc.usubjid, site_id=d.edc.site_id,
                observed=f"EDC: {d.edc_value}; central lab: {d.vendor_value}", expected=f"{d.detail} (central lab record transfer#{d.vendor.id})"))
        for e in res.edc_only:
            out[SPEC_ONE_SIDED].append(Failure(src_table="edc.lab", src_pk=str(e.id), usubjid=e.usubjid, site_id=e.site_id,
                                               observed=f"EDC: {e.test} {e.value} {e.unit or ''} on {e.day}; no central lab record", expected="a matching central lab record"))
        for v in res.vendor_only:
            out[SPEC_ONE_SIDED].append(Failure(src_table="lab_vendor.transfer", src_pk=str(v.id), usubjid=v.usubjid, site_id=v.usubjid.split("-")[1] if v.usubjid else None,
                                               observed=f"Central lab: {v.test} {v.value} {v.unit or ''} on {v.day}; no EDC result", expected=f"a matching EDC lab result (central lab record transfer#{v.id})"))
        if res.stale:
            out[SPEC_STALE].append(Failure(src_table="lab_vendor.transfer", src_pk="feed", usubjid=None, site_id=None,
                                           observed=f"Last central lab file: {res.last_file or 'none'}", expected="a file at least every 3 days while samples are being collected"))
        return out

    def run(self, day: date, lab_ids: set[int] | None = None, full: bool = False) -> dict:
        from app.checks.runner import CheckRunner
        subjects = None if full else self.affected_subjects(day, lab_ids or set())
        res = self.compute(day, subjects)
        runner = CheckRunner(self.conn)
        new = 0
        for spec_id, fails in self.failures(res).items():
            if spec_id == SPEC_STALE or subjects is None:
                new += runner._apply(spec_id, fails, None, None, day)
            else:
                new += runner.apply_scoped(spec_id, fails, sorted(subjects), day)
        return {"matched": res.matched, "value": sum(d.kind == "value" for d in res.diffs), "unit": sum(d.kind == "unit" for d in res.diffs),
                "edc_only": len(res.edc_only), "vendor_only": len(res.vendor_only), "stale": res.stale, "new_failures": new,
                "subjects": None if subjects is None else len(subjects)}
