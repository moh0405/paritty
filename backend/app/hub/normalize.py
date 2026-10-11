"""Identifier normalization for the external feeds (spec §9.9): strip prefixes, repair look-alike characters, zero-pad, lowercase names."""
from __future__ import annotations

import re
from dataclasses import dataclass

_LOOKALIKE = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1"})
_DIG = r"([0-9OolI|]{3,4})"
_LAB = re.compile(rf"^\s*[Pp][Tt]\s*[-_ ]?\s*{_DIG}\s*[-_ ]\s*{_DIG}\s*$")     # the separator between site and subject is mandatory: PT7011015 is ambiguous
_SAFETY = re.compile(rf"^\s*[Ss][Uu][Bb][Jj]\s*{_DIG}\s*[/\\-]?\s*[Ss][Ii][Tt][Ee]\s*{_DIG}\s*$")
_IRT = re.compile(rf"^\s*[Rr]\s*[-_ ]?\s*{_DIG}\s*[-_ ]\s*{_DIG}\s*$")
_SITE_CODE = re.compile(r"^\s*SITE[-_ ]*0*(\d+)([A-Za-z]?)\s*$", re.I)


def fix_digits(s: str) -> str:
    return s.translate(_LOOKALIKE)


@dataclass(frozen=True)
class SubjectKey:
    site: str
    number: str          # as written, repaired; IRT numbers may be only the last three digits
    repaired: bool = False

    @property
    def usubjid(self) -> str:
        return f"01-{self.site}-{self.number}"


def parse_lab_ref(ref: str | None) -> SubjectKey | None:
    """'PT701-1015' -> site 701, subject 1015 (tolerates look-alike characters, spacing, case)."""
    m = _LAB.match(ref or "")
    return SubjectKey(fix_digits(m.group(1)), fix_digits(m.group(2)), repaired=bool(set(m.group(1) + m.group(2)) & set("OolI|"))) if m else None


def parse_safety_ref(ref: str | None) -> SubjectKey | None:
    """'SUBJ 1015 / SITE 701' -> site 701, subject 1015."""
    m = _SAFETY.match(ref or "")
    return SubjectKey(fix_digits(m.group(2)), fix_digits(m.group(1)), repaired=bool(set(m.group(1) + m.group(2)) & set("OolI|"))) if m else None


def parse_irt_ref(ref: str | None) -> SubjectKey | None:
    """'R-701-015' -> site 701, last three digits 015 (ambiguous until matched against the site's subjects)."""
    m = _IRT.match(ref or "")
    return SubjectKey(fix_digits(m.group(1)), fix_digits(m.group(2)), repaired=bool(set(m.group(1) + m.group(2)) & set("OolI|"))) if m else None


def parse_site_code(code: str | None) -> tuple[str, str] | None:
    """'SITE-0701' -> ('701', ''); 'SITE-0711B' -> ('711', 'B') (the suffix marks a duplicate record)."""
    m = _SITE_CODE.match(code or "")
    return (m.group(1), m.group(2).upper()) if m else None


_NAME_WORDS = {"cln": "clinic", "ctr": "center", "inst": "institute", "assoc": "associates"}


def norm_site_name(name: str | None) -> str:
    """Lowercase, drop 'the', company suffixes and punctuation, expand common abbreviations."""
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().replace("l.l.c.", "llc"))
    words = [_NAME_WORDS.get(w, w) for w in s.split() if w not in ("the", "llc", "inc", "ltd")]
    return " ".join(words)
