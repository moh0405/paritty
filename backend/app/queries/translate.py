"""Query translation (spec §9.3): the translation is blocked if any number, date or identifier of the source is missing from it."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.llm import prompts
from app.llm.client import LLMClient, get_client
from app.llm.schemas import Translation
from app.verification.normalize import extract_dates

LANGUAGES = ["Spanish", "French", "German", "Italian", "Portuguese", "Dutch", "Polish", "Japanese", "Chinese (Simplified)"]
_TOKEN = re.compile(r"\b[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)+\b")


def identifiers(text: str) -> list[str]:
    """Hyphenated codes that must survive translation whole: 01-701-1015, PT701-1015, K-000123. A plain range such as 60-250 is not an identifier."""
    return [t for t in _TOKEN.findall(text) if re.search(r"[A-Za-z]", t) or len(re.split(r"[-/]", t)) >= 3]


class TranslationBlocked(Exception):
    def __init__(self, issues: list[str]):
        super().__init__("; ".join(issues))
        self.issues = issues


class TranslationUnavailable(Exception):
    pass


def facts(text: str) -> list[str]:
    """Everything that must survive translation exactly: dates, identifiers and numbers (as written)."""
    ids = identifiers(text)
    rest = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text)
    for i in ids:
        rest = rest.replace(i, " ")
    return extract_dates(text) + ids + re.findall(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])", rest)


def check(source: str, translated: str) -> list[str]:
    """Every date, identifier and number of the source must appear unchanged in the translation (spec §9.3)."""
    return [f"'{m}' from the original is missing or changed" for m in dict.fromkeys(f for f in facts(source) if f not in translated)]


@dataclass
class TranslationResult:
    text: str
    language: str
    source_text: str
    issues: list[str] = field(default_factory=list)


class QueryTranslator:
    def __init__(self, client: LLMClient | None = None, conn=None):
        self.client = client if client is not None else get_client()
        self.conn = conn

    def translate(self, text: str, language: str) -> TranslationResult:
        if language not in LANGUAGES:
            raise ValueError(f"language must be one of {', '.join(LANGUAGES)}")
        version, prompt = prompts.render("translate_query", language=language, text=text)
        try:
            res = self.client.structured("translate_query", prompt, Translation, prompt_version=version, conn=self.conn)
        except Exception as exc:
            raise TranslationUnavailable(f"Translation needs the AI service, which is not available right now ({type(exc).__name__}).")
        if res.parsed is None:
            raise TranslationUnavailable("Translation needs the AI service, and no recorded translation exists for this text.")
        out = res.parsed.text.strip()
        issues = check(text, out)
        if issues:
            raise TranslationBlocked(issues)
        return TranslationResult(out, language, text)
