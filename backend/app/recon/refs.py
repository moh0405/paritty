"""Identifier handling for external feeds. Milestone 11 replaces this with the hub crosswalk (hub.subject_xwalk);
until then the two formats the mock systems use are parsed deterministically."""
from __future__ import annotations

import re

_SAFETY_REF = re.compile(r"^\s*SUBJ\s+(\d+)\s*/\s*SITE\s+(\d+)\s*$", re.I)


def usubjid_from_safety_ref(ref: str) -> str | None:
    """'SUBJ 1015 / SITE 701' -> '01-701-1015'"""
    m = _SAFETY_REF.match(ref or "")
    return f"01-{m.group(2)}-{m.group(1)}" if m else None
