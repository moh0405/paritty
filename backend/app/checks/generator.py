"""CheckGenerator (spec §9.2): protocol text -> EditCheckSpec proposals -> validate -> dry run -> pending approval.
Gemini proposes when available; a deterministic extractor covers the protocol's numeric limits so the feature works without it.
Nothing runs until a human approves it."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from psycopg import Connection

from app.audit.logger import audit
from app.checks.base import EditCheckSpec
from app.checks.factory import CheckFactory, SpecError
from app.llm import prompts
from app.llm.client import LLMClient, get_client
from app.llm.schemas import CheckSpecProposal, ProposedCheck
from app.verification.normalize import norm_ws

ALLOWED_TYPES = {"range", "date_order"}


@dataclass
class Generated:
    id: str
    status: str                       # pending_approval | rejected
    reason: str = ""
    description: str = ""
    quote: str = ""
    chunk_id: int | None = None
    dry_run_count: int | None = None
    sample: list[str] = field(default_factory=list)
    source: str = ""


def _sentence(text: str, start: int, end: int) -> str:
    a = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    b = text.find(".", end)
    return text[a + 1 if a >= 0 else 0:(b + 1) if b >= 0 else len(text)].strip(" \n")


def extract_rules(chunk_id: int, text: str) -> list[ProposedCheck]:
    """Deterministic extraction of the numeric limits the protocol states in plain sentences."""
    out: list[ProposedCheck] = []

    def add(suffix, params, desc, ctq, sev, m):
        out.append(ProposedCheck(id_suffix=suffix, type="range", params_json=json.dumps(params), description=desc, ctq_category=ctq, severity=sev,
                                 quote=_sentence(text, m.start(), m.end()), chunk_id=chunk_id))

    if m := re.search(r"between (\d+) and (\d+) years of age", text):
        add("age", {"table": "edc.subjects", "column": "age", "min": int(m.group(1)), "max": int(m.group(2))},
            f"Age at consent outside {m.group(1)}-{m.group(2)} years (protocol eligibility)", "eligibility", "critical", m)
    if m := re.search(r"systolic blood pressure at Screening 1 must be below (\d+) mmHg", text, re.I):
        add("screening_sbp", {"table": "edc.vitals", "column": "value", "test_code": "SYSBP", "visit": "SCREENING 1", "min": None, "max": float(m.group(1)) - 0.01},
            f"Screening systolic blood pressure is not below {m.group(1)} mmHg (protocol eligibility)", "eligibility", "critical", m)
    if m := re.search(r"\(ALT\) at Screening 1 must not exceed (\d+(?:\.\d+)?) times", text):
        add("screening_alt", {"table": "edc.lab", "column": "x_uln", "test_code": "ALT", "visit": "SCREENING 1", "min": None, "max": float(m.group(1))},
            f"Screening ALT exceeds {m.group(1)} times the upper limit of normal (protocol eligibility)", "eligibility", "critical", m)
    if m := re.search(r"[Tt]otal bilirubin at Screening 1 must not exceed (\d+(?:\.\d+)?) times", text):
        add("screening_bili", {"table": "edc.lab", "column": "x_uln", "test_code": "BILI", "visit": "SCREENING 1", "min": None, "max": float(m.group(1))},
            f"Screening total bilirubin exceeds {m.group(1)} times the upper limit of normal (protocol eligibility)", "eligibility", "critical", m)
    return out


class CheckGenerator:
    def __init__(self, conn: Connection, client: LLMClient | None = None):
        self.conn = conn
        self.client = client if client is not None else get_client()
        self.factory = CheckFactory()

    def chunks(self) -> list[tuple[int, str, str]]:
        return self.conn.execute("SELECT id, section, text FROM ai.protocol_chunks ORDER BY id").fetchall()

    def propose(self, use_llm: bool) -> tuple[list[ProposedCheck], str]:
        chunks = self.chunks()
        if use_llm:
            try:
                version, prompt = prompts.render("check_generation", chunks_json=json.dumps([{"id": i, "section": s, "text": t} for i, s, t in chunks], indent=1))
                res = self.client.structured("check_generation", prompt, CheckSpecProposal, model=None, prompt_version=version, conn=self.conn)
                if res.parsed is not None and res.parsed.checks:
                    return res.parsed.checks, "gemini"
            except Exception as exc:
                print(f"warning: check generation by LLM failed ({type(exc).__name__}); using the rule extractor")
        return [p for cid, _s, text in chunks for p in extract_rules(cid, text)], "rule_extractor"

    def validate(self, p: ProposedCheck, source: str, chunk_text: dict[int, str]) -> tuple[EditCheckSpec | None, Generated]:
        gid = f"gen_{re.sub(r'[^a-z0-9_]', '_', p.id_suffix.lower())}"
        g = Generated(gid, "rejected", description=p.description, quote=p.quote, chunk_id=p.chunk_id, source=source)
        if p.type not in ALLOWED_TYPES:
            g.reason = f"check type '{p.type}' is not supported for generated checks"
            return None, g
        if p.chunk_id not in chunk_text or norm_ws(p.quote) not in norm_ws(chunk_text[p.chunk_id]):
            g.reason = "the quoted sentence is not in the cited protocol chunk"
            return None, g
        try:
            spec = EditCheckSpec(id=gid, type=p.type, params=json.loads(p.params_json), description=p.description, ctq_category=p.ctq_category,
                                 severity=p.severity, source="generated", approval_status="pending_approval", active=True,
                                 rationale={"quote": p.quote, "chunk_id": p.chunk_id, "proposed_by": source})
            compiled = self.factory.compile(spec)
            fails = compiled.run(self.conn)
        except (SpecError, ValueError, KeyError, TypeError) as exc:
            g.reason = f"the specification is invalid: {exc}"
            return None, g
        g.status, g.dry_run_count, g.sample = "pending_approval", len(fails), [f.src_pk for f in fails[:5]]
        assert spec.rationale is not None
        spec.rationale.update(dry_run_count=len(fails), dry_run_sample=g.sample)
        return spec, g

    def generate(self, use_llm: bool = True, actor: str = "system", day=None) -> list[Generated]:
        proposals, source = self.propose(use_llm)
        texts = {i: t for i, _s, t in self.chunks()}
        out: list[Generated] = []
        for p in proposals:
            spec, g = self.validate(p, source, texts)
            out.append(g)
            if spec is None:
                continue
            created = self.conn.execute(
                "INSERT INTO ops.check_specs (id, type, params, ctq_category, severity, source, approval_status, rationale, active) VALUES (%s,%s,%s,%s,%s,%s,'pending_approval',%s,true) "
                "ON CONFLICT (id) DO NOTHING", (spec.id, spec.type, json.dumps({**spec.params, "_description": spec.description}), spec.ctq_category, spec.severity,
                                                spec.source, json.dumps(spec.rationale))).rowcount
            if created:
                audit(self.conn, day, actor, "check.proposed", "check_spec", spec.id, {"source": source, "dry_run_count": g.dry_run_count})
            else:
                g.reason = "already proposed"
        return out
