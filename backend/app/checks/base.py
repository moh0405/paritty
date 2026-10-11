"""Edit-check specs (spec §9.2). A spec is data; the factory turns it into SQL over an allow-list."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CheckType = Literal["range", "unit_plausibility", "date_order", "required_field", "visit_window", "missing_visit",
                    "duplicate", "cross_form", "external_lab"]
Ctq = Literal["safety", "efficacy", "eligibility", "other"]
Severity = Literal["critical", "major", "minor"]


class EditCheckSpec(BaseModel):
    id: str
    type: CheckType
    params: dict
    description: str
    ctq_category: Ctq = "other"
    severity: Severity = "minor"
    source: str = "library"
    approval_status: Literal["approved", "pending_approval", "rejected"] = "approved"
    rationale: dict | None = None
    active: bool = True


class Failure(BaseModel):
    src_table: str
    src_pk: str
    usubjid: str | None
    site_id: str | None
    observed: str | None
    expected: str | None
