"""Structured outputs Gemini must return (spec §10). Kept to plain types so they work as response schemas."""
from typing import Literal

from pydantic import BaseModel


class Citation(BaseModel):
    table: str        # e.g. "edc.vitals"
    pk: str           # primary key of the cited row, as text
    column: str
    value: str        # the cell value, copied exactly
    quote: str | None = None   # optional exact substring of the cell


class Claim(BaseModel):
    text: str
    citations: list[Citation]


class FindingOut(BaseModel):
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    claims: list[Claim]


class QueryDraft(BaseModel):
    query_text: str      # what the site will read
    claims: list[Claim]  # the facts the text relies on, each cited


class TermDecision(BaseModel):
    """Adjudication of whether two adverse event terms describe the same event (grey-zone term matching)."""
    same_event: bool
    confidence: float
    reason: str


class ProposedCheck(BaseModel):
    id_suffix: str
    type: str                # range | date_order | required_field | unit_plausibility | duplicate
    params_json: str         # the spec's params as a JSON object (kept as text so the response schema stays simple)
    description: str
    ctq_category: Literal["safety", "efficacy", "eligibility", "other"]
    severity: Literal["critical", "major", "minor"]
    quote: str               # exact sentence from the protocol chunk that justifies the check
    chunk_id: int


class CheckSpecProposal(BaseModel):
    checks: list[ProposedCheck]


class XwalkDecision(BaseModel):
    """Which candidate subject (or site) an unmatched source identifier refers to, if any."""
    chosen: str            # one of the candidate ids, or "none"
    confidence: float
    reason: str


class Quote(BaseModel):
    chunk_id: int
    text: str            # must be an exact substring of that protocol chunk


class QAAnswer(BaseModel):
    answer: str
    quotes: list[Quote]
    escalate: bool       # true when the protocol does not settle the question or it needs medical judgment
    confidence: float


class ReviewNote(BaseModel):
    summary: str         # a short note for the medical monitor, in neutral wording
    claims: list[Claim]


class CausalityOut(BaseModel):
    """Simplified WHO-UMC causality assessment with cited evidence (spec §9.5)."""
    category: Literal["certain", "probable", "possible", "unlikely", "unassessable"]
    confidence: float
    evidence: list[Claim]
    alternative_causes: list[str]
    escalate: bool


class EvalSummary(BaseModel):
    """A plain-English summary of an evaluation run; every claim cites the metric rows it reports."""
    text: str
    claims: list[Claim]


class Translation(BaseModel):
    text: str


class SqlProposal(BaseModel):
    sql: str
    explanation: str
    refuse: bool = False       # true when the question cannot be answered from the allowed views


class AgentChoice(BaseModel):
    candidate_id: str
    rationale: str


class AgentPlan(BaseModel):
    actions: list[AgentChoice]

class VisitAgenda(BaseModel):
    """Agenda for a monitoring visit or call with one site."""
    text: str            # what the monitor will read and take to the site
    claims: list[Claim]  # the facts the text relies on, each cited


class FollowUpLetter(VisitAgenda):
    """Follow-up letter to a site after central review; same shape as an agenda."""
