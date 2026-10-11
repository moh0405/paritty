"""DiscrepancyClassifier (spec §9.5 table): acceptable / actionable / critical per field and per pair."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.recon.sae.matcher import AeRec, CaseRec, Match

OUTCOME_E2B = {"RECOVERED/RESOLVED": "1", "RECOVERING/RESOLVING": "2", "NOT RECOVERED/NOT RESOLVED": "3",
               "RECOVERED/RESOLVED WITH SEQUELAE": "4", "FATAL": "5", "UNKNOWN": "6"}
E2B_OUTCOME_LABEL = {v: k for k, v in OUTCOME_E2B.items()}
RELATED = {"PROBABLE", "POSSIBLE"}
NOT_RELATED = {"REMOTE", "NONE"}
RANK = {"clean": 0, "acceptable": 1, "actionable": 2, "critical": 3}
EDC_ONLY_GRACE_DAYS = 3   # protocol: SAEs are reported within 24 h; allow a few days before an unreported AE is flagged

SPEC_FOR_FIELD = {"onset": "sae_onset", "term": "sae_term", "seriousness": "sae_seriousness", "causality": "sae_causality",
                  "outcome": "sae_outcome", "death": "sae_death"}


@dataclass
class Discrepancy:
    field: str
    edc_value: str | None
    safety_value: str | None
    cls: str              # acceptable | actionable | critical
    reason: str

    @property
    def spec_id(self) -> str:
        return SPEC_FOR_FIELD[self.field]    # only actionable/critical fields have a spec; "narrative" is acceptable-only


@dataclass
class PairResult:
    match: Match
    discrepancies: list[Discrepancy] = field(default_factory=list)

    @property
    def overall(self) -> str:
        return max((d.cls for d in self.discrepancies), key=RANK.__getitem__, default="clean")

    @property
    def needs_causality(self) -> bool:
        return any(d.field == "causality" and d.cls == "actionable" and d.safety_value and d.edc_value for d in self.discrepancies)


@dataclass
class OneSided:
    kind: str                      # edc_only | safety_only
    cls: str                       # actionable | critical
    reason: str
    ae: AeRec | None = None
    case: CaseRec | None = None
    pending: bool = False          # inside the reporting grace period: not yet a discrepancy


def edc_causality(c: str | None) -> str | None:
    return "Related" if c in RELATED else ("Not related" if c in NOT_RELATED else None)


def edc_fatal(ae: AeRec) -> bool:
    return ae.outcome == "FATAL"


def case_fatal(c: CaseRec) -> bool:
    return c.death == "1" or c.outcome == "5"


class DiscrepancyClassifier:
    def classify_pair(self, m: Match) -> PairResult:
        ae, case, res = m.ae, m.case, PairResult(m)
        add = lambda *a: res.discrepancies.append(Discrepancy(*a))  # noqa: E731

        # onset
        if ae.onset and case.onset:
            delta = abs((ae.onset - case.onset).days)
            if delta > 1:
                add("onset", str(ae.onset), str(case.onset), "actionable", f"onset dates differ by {delta} days")
            elif delta == 1:
                add("onset", str(ae.onset), str(case.onset), "acceptable", "onset dates differ by 1 day")
        elif ae.onset != case.onset:
            add("onset", str(ae.onset) if ae.onset else None, str(case.onset) if case.onset else None, "actionable", "onset date missing on one side")
        # term
        if m.term.method != "exact":
            if m.term.same:
                add("term", ae.term_coded, case.term, "acceptable", "different wording, same coded term")
            else:
                add("term", ae.term_coded, case.term, "actionable", "different coded term")
        # seriousness
        if (case.serious == "1") != ae.serious:
            add("seriousness", "serious" if ae.serious else "not serious", "serious" if case.serious == "1" else "not serious",
                "actionable", "seriousness differs")
        # causality
        e, s = edc_causality(ae.causality), case.causality
        if e != s:
            add("causality", e, s, "actionable", "causality missing on one side" if not (e and s) else "causality differs")
        # death vs outcome
        if edc_fatal(ae) != case_fatal(case):
            add("death", "fatal" if edc_fatal(ae) else "not fatal", "fatal" if case_fatal(case) else "not fatal", "critical", "death recorded on one side only")
        else:
            e_out, s_out = OUTCOME_E2B.get(ae.outcome or ""), case.outcome
            if not e_out or not s_out:
                add("outcome", ae.outcome, E2B_OUTCOME_LABEL.get(s_out or "", None), "actionable", "outcome missing on one side")
            elif e_out != s_out:
                follow_up = case.version > 1
                add("outcome", ae.outcome, E2B_OUTCOME_LABEL.get(s_out), "acceptable" if follow_up else "actionable",
                    "safety database is newer (follow-up version)" if follow_up else "outcomes differ")
        if case.version > 1 and "Follow-up:" in (case.narrative or ""):
            add("narrative", None, "follow-up detail", "acceptable", "safety has extra narrative detail")
        return res

    def classify_unmatched(self, aes: list[AeRec], cases: list[CaseRec], today: date) -> list[OneSided]:
        out: list[OneSided] = []
        for ae in aes:
            pending = ae.entered_at + timedelta(days=EDC_ONLY_GRACE_DAYS) > today
            out.append(OneSided("edc_only", "critical" if edc_fatal(ae) else "actionable",
                                "serious AE in EDC with no safety case" + (" (fatal)" if edc_fatal(ae) else ""), ae=ae, pending=pending))
        for c in cases:
            out.append(OneSided("safety_only", "critical" if case_fatal(c) else "actionable",
                                "safety case with no serious AE in EDC" + (" (fatal)" if case_fatal(c) else ""), case=c))
        return out
