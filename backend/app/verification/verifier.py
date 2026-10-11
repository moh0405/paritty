"""Verifier (spec §11). A claim is verified when every check passes; a finding/draft is
verified (all claims), partial (>=1 verified, none contradicted) or blocked."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.schemas import Claim
from app.verification import checks as ck
from app.verification.checks import CheckResult, VerifyContext


@dataclass
class ClaimResult:
    idx: int
    status: str                    # verified | unsupported | contradicted
    checks: list[CheckResult] = field(default_factory=list)


@dataclass
class VerificationResult:
    status: str                    # verified | partial | blocked
    claims: list[ClaimResult]

    @property
    def grounding_rate(self) -> float:
        return sum(c.status == "verified" for c in self.claims) / len(self.claims) if self.claims else 0.0


class Verifier:
    def verify_claim(self, idx: int, claim: Claim, ctx: VerifyContext) -> ClaimResult:
        results: list[CheckResult] = []
        if not claim.citations:
            results.append(CheckResult("HasCitations", False, "claim cites no evidence"))
        for c in claim.citations:
            for r in (ck.evidence_subset(c, ctx), ck.row_exists(c, ctx), ck.role_visible(c, ctx), ck.value_matches(c, ctx),
                      ck.quote_in_source(c, ctx)):
                if r is not None:
                    r.detail = f"[{c.table}#{c.pk}.{c.column}] {r.detail}".strip() if r.detail else r.detail
                    results.append(r)
        results.append(ck.claim_numbers_covered(claim.text, claim.citations, ctx))
        failed = [r for r in results if not r.passed]
        status = "verified" if not failed else ("contradicted" if any(r.kind == "contradicted" for r in failed) else "unsupported")
        return ClaimResult(idx, status, results)

    def verify(self, claims: list[Claim], ctx: VerifyContext) -> VerificationResult:
        results = [self.verify_claim(i, c, ctx) for i, c in enumerate(claims)]
        verified = [r for r in results if r.status == "verified"]
        if results and len(verified) == len(results):
            status = "verified"
        elif verified and not any(r.status == "contradicted" for r in results):
            status = "partial"
        else:
            status = "blocked"
        return VerificationResult(status, results)
