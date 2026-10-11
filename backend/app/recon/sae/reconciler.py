"""SaeReconciler: match, classify, and keep ops.check_failures + history in step with the data (spec §9.1 step 4, §9.5)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from psycopg import Connection

from app.checks.base import Failure
from app.checks.runner import CheckRunner
from app.llm.client import LLMClient, get_client
from app.hub.crosswalk import SubjectMap
from app.recon.sae.causality import CausalityAssessor
from app.recon.sae.classifier import RANK, DiscrepancyClassifier, OneSided, PairResult
from app.recon.sae.matcher import AeRec, CaseRec, HybridTermMatcher, SaeMatcher
from app.recon.sae.specs import SAE_SPEC_IDS


@dataclass
class ReconResult:
    day: date
    pairs: list[PairResult] = field(default_factory=list)
    one_sided: list[OneSided] = field(default_factory=list)

    def counts(self) -> dict:
        c = {"pairs": len(self.pairs), "clean": 0, "acceptable": 0, "actionable": 0, "critical": 0,
             "edc_only": 0, "safety_only": 0, "pending": 0, "needs_causality": 0}
        for p in self.pairs:
            c[p.overall] += 1
            c["needs_causality"] += p.needs_causality
        for o in self.one_sided:
            if o.pending:
                c["pending"] += 1
            else:
                c[o.kind] += 1
        c["open_discrepancies"] = c["actionable"] + c["critical"] + c["edc_only"] + c["safety_only"]
        return c


class SaeReconciler:
    def __init__(self, conn: Connection, client: LLMClient | None = None):
        self.conn = conn
        self.client = client if client is not None else get_client()

    def load(self, day: date) -> tuple[list[AeRec], list[CaseRec]]:
        aes = [AeRec(r[0], r[1], r[2], r[3], r[4], bool(r[5]), r[6], r[7], r[8]) for r in self.conn.execute(
            "SELECT id, usubjid, site_id, term_coded, onset_at, serious, causality, outcome, entered_at FROM edc.ae WHERE serious ORDER BY id")]
        smap = SubjectMap(self.conn)
        cases = [CaseRec(r[0], r[1], r[2], smap.get("safety", r[3]), r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12])
                 for r in self.conn.execute(
            "SELECT DISTINCT ON (safetyreportid) id, safetyreportid, version, subject_ref, reaction_term, onset, serious, causality, outcome, "
            "death, received, available_on, narrative FROM safety.v_cases WHERE available_on <= %s ORDER BY safetyreportid, version DESC", (day,))]
        return aes, cases

    def compute(self, day: date, allow_llm: bool = False) -> ReconResult:
        aes, cases = self.load(day)
        terms = HybridTermMatcher(self.conn, self.client, allow_llm=allow_llm)
        matches, edc_only, safety_only = SaeMatcher(terms).match(aes, cases)
        clf = DiscrepancyClassifier()
        return ReconResult(day, [clf.classify_pair(m) for m in matches], clf.classify_unmatched(edc_only, safety_only, day))

    # ---- failures ---------------------------------------------------------------------------------
    def failures(self, res: ReconResult) -> dict[str, list[Failure]]:
        out: dict[str, list[Failure]] = {sid: [] for sid in SAE_SPEC_IDS}
        for p in res.pairs:
            ae, case = p.match.ae, p.match.case
            for d in p.discrepancies:
                if d.cls == "acceptable":
                    continue
                out[d.spec_id].append(Failure(src_table="edc.ae", src_pk=str(ae.id), usubjid=ae.usubjid, site_id=ae.site_id,
                                              observed=f"EDC: {d.edc_value or 'missing'}; safety: {d.safety_value or 'missing'}",
                                              expected=f"{d.reason} (safety case v_cases#{case.row_id})"))
        for o in res.one_sided:
            if o.pending:
                continue
            fatal = o.cls == "critical"
            if o.kind == "edc_only":
                a = o.ae
                out["sae_fatal_one_sided" if fatal else "chk_22"].append(Failure(
                    src_table="edc.ae", src_pk=str(a.id), usubjid=a.usubjid, site_id=a.site_id,
                    observed=f"EDC: serious AE {a.term_coded} on {a.onset}; no matching safety case", expected="a safety case for this event"))
            else:
                c = o.case
                site = c.usubjid.split("-")[1] if c.usubjid else None
                out["sae_fatal_one_sided" if fatal else "sae_safety_only"].append(Failure(
                    src_table="safety.case_versions", src_pk=c.case_id, usubjid=c.usubjid, site_id=site,
                    observed=f"Safety: case {c.term} on {c.onset}; no matching serious AE in EDC",
                    expected=f"a serious AE in EDC (safety case v_cases#{c.row_id})"))
        return out

    def run(self, day: date, allow_llm: bool = True) -> dict:
        res = self.compute(day, allow_llm=allow_llm)
        runner = CheckRunner(self.conn)
        new = 0
        for spec_id, fails in self.failures(res).items():
            new += runner._apply(spec_id, fails, None, None, day)
        assessed = CausalityAssessor(self.conn, self.client).assess_conflicts(day, [p.match.case.case_id for p in res.pairs if p.needs_causality])
        counts = res.counts()
        self.conn.execute("INSERT INTO ops.sae_recon_history (sim_date, counts) VALUES (%s,%s) ON CONFLICT (sim_date) DO UPDATE SET counts = EXCLUDED.counts",
                          (day, json.dumps(counts)))
        return {**counts, "new_failures": new, "causality_assessed": assessed}
