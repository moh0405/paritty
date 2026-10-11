"""Normalization used by the verifier (spec §11): ISO dates, 2-dp numbers, case-folded trimmed strings."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal

ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?")
_IDENTIFIER = re.compile(r"\b\d{2}-\d{3}-\d{4}\b|\b[A-Za-z]+[-_]?\d[\w-]*\b")   # 01-701-1015, PT701-1015, K-000123
_RANGE_DASH = re.compile(r"(?<=\d)\s*[–—-]\s*(?=\d)")
_NUMBER = re.compile(r"(?<![\w.\-/])-?\d+(?:\.\d+)?(?![\d\-/]|\.\d)")   # allows unit suffixes: 5.25x, 300mmHg
_WS = re.compile(r"\s+")


def norm_ws(s: str) -> str:
    return _WS.sub(" ", s).strip()


def norm_cell(v) -> str:
    """Canonical text for comparing a cell with a cited value."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (int, float, Decimal)):
        return f"{round(float(v), 2):.2f}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True)
    s = norm_ws(str(v))
    m = ISO_DATE.fullmatch(s)
    if m:
        return m.group(1)
    try:
        return f"{round(float(s), 2):.2f}"
    except ValueError:
        return s.casefold()


def cell_text(v) -> str:
    """Source text for quote checks."""
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True)
    return str(v)


def extract_dates(text: str) -> list[str]:
    return ISO_DATE.findall(text)


def extract_numbers(text: str) -> list[float]:
    """Numbers in free text, ignoring ISO dates and identifiers such as 01-701-1015 or PT701-1015."""
    t = ISO_DATE.sub(" ", text)
    t = _IDENTIFIER.sub(" ", t)
    t = _RANGE_DASH.sub(" ", t)
    return [float(x) for x in _NUMBER.findall(t)]
