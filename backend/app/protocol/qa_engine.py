"""Protocol Q&A (spec §9.10): hybrid retrieval of protocol chunks, a quoted answer, and escalation when the protocol does not settle it.
Gemini answers when it can; every quote is verified as an exact substring of the retrieved chunk. Without Gemini a deterministic
extractive baseline quotes the best-matching sentence. Used by the eligibility assistant, the site concierge and check generation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from psycopg import Connection

from app.llm import prompts
from app.llm.client import LLMClient, get_client
from app.llm.schemas import QAAnswer
from app.search.hybrid import ChunkSearch
from app.verification.normalize import norm_ws

MIN_CONFIDENCE = 0.6
MIN_COVERAGE = 0.2      # below this the closest sentence shares too little with the question to be an answer
TOP_K = 6
STOP = set("a an the and or of to in on at for is are be do does can we our this that with it its if as by from what when how many much which who whom should would could may must have has had".split())
# Questions that ask for a medical or procedural judgment about a specific patient rather than for a rule: always escalate.
JUDGMENT_CUES = re.compile(
    r"\b(ok|okay|acceptable|suitable|reliable enough|good enough|still (count|enrol|enroll|eligible|stay)|stay in the study|should we|waive|"
    r"count (it|them|him|her) as|otherwise|unblind|one-off|a minor|features?|exception)\b", re.I)


@dataclass
class QAResult:
    question: str
    answer: str
    quotes: list[dict] = field(default_factory=list)       # [{chunk_id, section, text}]
    escalate: bool = False
    confidence: float = 0.0
    reason: str = ""
    source: str = "extractive"                              # gemini | extractive
    retrieved: list[int] = field(default_factory=list)


ACRONYMS = {"sae": "serious adverse event", "saes": "serious adverse events", "ae": "adverse event", "aes": "adverse events", "edc": "case report form data",
            "icf": "informed consent", "uln": "upper limit of normal", "lft": "liver tests", "crf": "case report form", "bp": "blood pressure", "mmse": "mini-mental"}


def expand(text: str) -> str:
    return " ".join(ACRONYMS.get(w.lower().strip("?.,;:"), w) for w in text.split())


def stem(w: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[: -len(suffix)]
    return w


def tokens(text: str) -> set[str]:
    return {stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1}


def sentences(text: str) -> list[str]:
    out = []
    for block in re.split(r"\n+", text):
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", block):
            s = s.strip().lstrip("*- ").strip()
            if re.match(r"^\d+\.\s", s) or re.search(r"\[(SYNTHETIC|REAL)", s):       # section headings are not answers
                continue
            if len(s.split()) >= 4 and not s.startswith("#"):
                out.append(s)
    return out


class ProtocolQA:
    def __init__(self, conn: Connection, client: LLMClient | None = None, allow_live_embedding: bool = True):
        self.conn = conn
        self.client = client if client is not None else get_client()
        self.allow_live = allow_live_embedding

    def retrieve(self, question: str) -> list[dict]:
        res = ChunkSearch(self.conn).search(question, k=TOP_K, allow_live=self.allow_live)
        return [{"chunk_id": h.id, "section": h.term, "text": h.coded_term} for h in res.fused]

    # ---- Gemini path ------------------------------------------------------------------------------------
    def _gemini(self, question: str, chunks: list[dict]) -> QAResult | None:
        try:
            version, prompt = prompts.render("protocol_qa", question=question, chunks_json=json.dumps(chunks, indent=1))
            res = self.client.structured("protocol_qa", prompt, QAAnswer, prompt_version=version, conn=self.conn)
        except Exception as exc:
            print(f"warning: protocol QA fell back to extraction ({type(exc).__name__})")
            return None
        if res.parsed is None:
            return None
        a: QAAnswer = res.parsed
        by_id = {c["chunk_id"]: c for c in chunks}
        good = []
        for q in a.quotes:
            c = by_id.get(q.chunk_id)
            if c and q.text.strip() and norm_ws(q.text) in norm_ws(c["text"]):
                good.append({"chunk_id": q.chunk_id, "section": c["section"], "text": q.text})
        why = []
        if not good:
            why.append("no quote could be verified in the protocol")
        if a.confidence < MIN_CONFIDENCE:
            why.append(f"confidence {a.confidence:.2f} is below {MIN_CONFIDENCE}")
        if a.escalate:
            why.append("the model judged that this needs a person")
        return QAResult(question, a.answer, good, bool(why), a.confidence, "; ".join(why), "gemini", [c["chunk_id"] for c in chunks])

    # ---- deterministic baseline -----------------------------------------------------------------------
    def _extractive(self, question: str, chunks: list[dict]) -> QAResult:
        q = tokens(expand(question))
        sents = [(s, c, tokens(s)) for c in chunks for s in sentences(c["text"])]
        df = {w: sum(w in st for _, _, st in sents) for w in q}
        weight = {w: 1.0 / (1 + df[w]) for w in q}                      # a term found in few sentences says more than a common one
        total = sum(weight.values()) or 1.0
        best: tuple[float, str, dict] | None = None
        for s, c, st in sents:
            score = sum(weight[w] for w in q & st) / total
            if best is None or score > best[0]:
                best = (score, s, c)
        ids = [c["chunk_id"] for c in chunks]
        if best is None:
            return QAResult(question, "The protocol does not address this.", [], True, 0.0, "nothing relevant was found", "extractive", ids)
        score, sent, chunk = best
        why = []
        if score < MIN_COVERAGE:
            why.append(f"the closest protocol sentence only covers {score:.0%} of the question's terms")
        if JUDGMENT_CUES.search(question):
            why.append("the question asks for a judgment about a specific patient")
        return QAResult(question, f"The protocol says: {sent}", [{"chunk_id": chunk["chunk_id"], "section": chunk["section"], "text": sent}],
                        bool(why), round(score, 2), "; ".join(why), "extractive", ids)

    def ask(self, question: str) -> QAResult:
        chunks = self.retrieve(question)
        if not chunks:
            return QAResult(question, "The protocol does not address this.", [], True, 0.0, "no protocol text was found", "extractive")
        result = self._gemini(question, chunks) or self._extractive(question, chunks)
        if JUDGMENT_CUES.search(question) and not result.escalate:      # a judgment question is never answered by a quote alone
            result.escalate = True
            result.reason = (result.reason + "; " if result.reason else "") + "the question asks for a judgment about a specific patient"
        return result
