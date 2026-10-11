"""SAE matching (spec §9.5): HybridTermMatcher scores two AE terms; SaeMatcher pairs EDC serious AEs with safety cases."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import numpy as np
from psycopg import Connection
from scipy.optimize import linear_sum_assignment

from app.llm import prompts
from app.llm.client import LLMClient
from app.llm.schemas import TermDecision
from app.search.terms import TermIndex, cosine, norm_term

SAME_THRESHOLD, GREY_LOW = 0.8, 0.5          # below GREY_LOW: different; GREY_LOW..SAME_THRESHOLD: ask the adjudicator
MATCH_THRESHOLD = 0.35                       # pairs scoring below this are rejected
TERM_WEIGHT, DATE_WEIGHT, DATE_SPAN_DAYS = 0.6, 0.4, 30


@dataclass
class TermScore:
    score: float
    method: str          # exact | dictionary | decision | semantic | adjudicated | grey_unadjudicated
    reason: str = ""

    @property
    def same(self) -> bool:
        return self.score >= SAME_THRESHOLD


def _tokens(t: str) -> set[str]:
    return {w[:-1] if w.endswith("S") and len(w) > 3 else w for w in re.findall(r"[A-Z]+", t.upper())}


class HybridTermMatcher:
    """exact -> dictionary/synonym -> cached decision -> embedding similarity; the 0.5-0.8 grey zone goes to Gemini, once per pair."""

    def __init__(self, conn: Connection, client: LLMClient | None = None, allow_llm: bool = False):
        self.conn, self.client, self.allow_llm = conn, client, allow_llm
        self.index = TermIndex(conn)
        self._memo: dict[tuple[str, str], TermScore] = {}

    def score(self, a: str | None, b: str | None) -> TermScore:
        a, b = norm_term(a), norm_term(b)
        if not a or not b:
            return TermScore(0.0, "exact", "a term is missing")
        if a == b:
            return TermScore(1.0, "exact")
        key = (a, b) if a < b else (b, a)
        if key not in self._memo:
            self._memo[key] = self._score(*key)
        return self._memo[key]

    def _score(self, a: str, b: str) -> TermScore:
        ca, cb = self.index.canonical(a), self.index.canonical(b)
        if ca and cb and ca == cb:
            return TermScore(0.95, "dictionary", f"both map to {ca}")
        row = self.conn.execute("SELECT same_event, confidence, reason FROM ai.term_decisions WHERE term_a = %s AND term_b = %s", (a, b)).fetchone()
        if row:
            return TermScore(max(0.9, float(row[1])) if row[0] else min(0.3, 1 - float(row[1])), "decision", row[2] or "")
        va, vb = self.index.vector(a), self.index.vector(b)
        lexical = len(_tokens(a) & _tokens(b)) / max(1, len(_tokens(a) | _tokens(b)))
        sim = max(cosine(va, vb) if va and vb else 0.0, lexical)
        if sim >= SAME_THRESHOLD:
            return TermScore(sim, "semantic", "very similar wording")
        if sim < GREY_LOW:
            return TermScore(sim, "semantic", "different terms")
        return self._adjudicate(a, b, sim, ca, cb)

    def _adjudicate(self, a: str, b: str, sim: float, ca: str | None, cb: str | None) -> TermScore:
        if not (self.allow_llm and self.client):
            return TermScore(sim, "grey_unadjudicated", "similarity is in the grey zone and no decision is cached")
        version, prompt = prompts.render("term_decision", term_a=a, term_b=b, canon_a=ca or "not in dictionary", canon_b=cb or "not in dictionary")
        try:
            res = self.client.structured("term_decision", prompt, TermDecision, prompt_version=version, conn=self.conn)
        except Exception as exc:
            print(f"warning: term adjudication failed ({type(exc).__name__}); leaving '{a}' / '{b}' undecided")
            return TermScore(sim, "grey_unadjudicated", "adjudicator unavailable")
        if res.parsed is None:
            return TermScore(sim, "grey_unadjudicated", "no cached decision (replay miss)")
        d: TermDecision = res.parsed
        conf = min(1.0, max(0.0, d.confidence))
        self.conn.execute("INSERT INTO ai.term_decisions (term_a, term_b, same_event, confidence, method, reason) VALUES (%s,%s,%s,%s,%s,%s) "
                          "ON CONFLICT (term_a, term_b) DO NOTHING", (a, b, d.same_event, conf, f"gemini:{res.model}", d.reason))
        return TermScore(max(0.9, conf) if d.same_event else min(0.3, 1 - conf), "adjudicated", d.reason)


@dataclass
class AeRec:
    id: int
    usubjid: str
    site_id: str
    term_coded: str
    onset: date | None
    serious: bool
    causality: str | None
    outcome: str | None
    entered_at: date


@dataclass
class CaseRec:
    row_id: int
    case_id: str
    version: int
    usubjid: str | None
    term: str | None
    onset: date | None
    serious: str | None
    causality: str | None
    outcome: str | None
    death: str | None
    received: date | None
    available_on: date
    narrative: str | None


@dataclass
class Match:
    ae: AeRec
    case: CaseRec
    score: float
    term: TermScore


class SaeMatcher:
    """Per subject: score = 0.6*term_sim + 0.4*max(0, 1-|delta days|/30), one-to-one by the Hungarian algorithm, reject < 0.35."""

    def __init__(self, terms: HybridTermMatcher):
        self.terms = terms

    def pair_score(self, ae: AeRec, case: CaseRec) -> tuple[float, TermScore]:
        t = self.terms.score(ae.term_coded, case.term)
        d = abs((ae.onset - case.onset).days) if ae.onset and case.onset else None
        date_sim = max(0.0, 1 - d / DATE_SPAN_DAYS) if d is not None else 0.0
        return TERM_WEIGHT * t.score + DATE_WEIGHT * date_sim, t

    def match(self, aes: list[AeRec], cases: list[CaseRec]) -> tuple[list[Match], list[AeRec], list[CaseRec]]:
        matches: list[Match] = []
        used_ae: set[int] = set()
        used_case: set[str] = set()
        by_subj_ae: dict[str, list[AeRec]] = {}
        by_subj_case: dict[str, list[CaseRec]] = {}
        for a in aes:
            by_subj_ae.setdefault(a.usubjid, []).append(a)
        for c in cases:
            by_subj_case.setdefault(c.usubjid or "", []).append(c)
        for subj, a_list in by_subj_ae.items():
            c_list = by_subj_case.get(subj, [])
            if not c_list:
                continue
            scores = [[self.pair_score(a, c) for c in c_list] for a in a_list]
            cost = -np.array([[s for s, _ in row] for row in scores])
            for i, j in zip(*linear_sum_assignment(cost)):
                s, t = scores[i][j]
                if s >= MATCH_THRESHOLD:
                    matches.append(Match(a_list[i], c_list[j], s, t))
                    used_ae.add(a_list[i].id)
                    used_case.add(c_list[j].case_id)
        return matches, [a for a in aes if a.id not in used_ae], [c for c in cases if c.case_id not in used_case]
