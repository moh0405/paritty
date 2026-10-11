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
