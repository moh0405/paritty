"""Query text via Gemini with verification, falling back to a deterministic template (spec §9.3, §11)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from psycopg import Connection

from app.checks import evidence as ev_mod
from app.config import get_settings
from app.domain.enums import Role
from app.llm import prompts
from app.llm.client import LLMClient, get_client
from app.llm.schemas import Claim, QueryDraft
from app.verification.checks import VerifyContext
from app.verification.store import save_finding
from app.verification.verifier import Verifier

VIEWER_ROLE = Role.DATA_MANAGER   # queries are read by data managers


@dataclass
class Drafted:
    text: str
    finding_id: str | None
    source: str                    # gemini | template


def template_text(description: str, usubjid: str, observed: str | None, expected: str | None, src_table: str) -> str:
    return (f"Subject {usubjid}: {description}. Recorded value: {observed or 'n/a'}; expected: {expected or 'n/a'} "
            f"(source: {src_table}). Please check the source documents and either correct the entry or explain why it is correct.")


class QueryDrafter:
    def __init__(self, conn: Connection, client: LLMClient | None = None):
        self.conn = conn
        self.client = client if client is not None else get_client()
        self.verifier = Verifier()

    def _ctx(self, ev: ev_mod.Evidence) -> VerifyContext:
        return VerifyContext(self.conn, VIEWER_ROLE, evidence=ev.keys(), rule_numbers=ev.rule_numbers, rule_dates=ev.rule_dates)

    def draft(self, failure: dict, spec: dict, day: date) -> Drafted:
        ev = ev_mod.build(self.conn, failure, spec)
        severity = {"critical": "critical", "major": "high", "minor": "low"}[spec["severity"]]
        tmpl = template_text(spec["description"], failure["usubjid"], failure["observed"], failure["expected"], failure["src_table"])
        meta = {"rule": ev.rule}
        # 1. Gemini draft, verified
        try:
            version, prompt = prompts.render("query_draft", check_description=spec["description"], expected=failure["expected"] or "n/a",
                                             observed=failure["observed"] or "n/a",
                                             evidence_json=json.dumps(ev.rows, default=str, indent=1))
            res = self.client.structured("query_draft", prompt, QueryDraft, prompt_version=version, conn=self.conn)
        except Exception as exc:   # live API trouble must never stop the simulation
            print(f"warning: query draft failed ({type(exc).__name__}: {exc}); using template")
            res = None
        if res is not None and res.parsed is not None:
            draft: QueryDraft = res.parsed
            citations = [c for cl in draft.claims for c in cl.citations]
            claims = [*draft.claims, Claim(text=draft.query_text, citations=citations)]   # the sent text is itself checked
            result = self.verifier.verify(claims, self._ctx(ev))
            fid = save_finding(self.conn, module="query_draft", rule_id=failure["check_id"], severity=severity, usubjid=failure["usubjid"],
                               site_id=failure["site_id"], title="Query draft", claims=claims, result=result, sim_date=day,
                               body_extra={**meta, "query_text": draft.query_text, "model": res.model, "source": "gemini"})
            if result.status == "verified":
                return Drafted(draft.query_text, fid, "gemini")
        # 2. deterministic template, with verifiable facts about the failing cell
        claims = ev_mod.template_claims(ev)
        result = self.verifier.verify(claims, self._ctx(ev))
        fid = save_finding(self.conn, module="checks", rule_id=failure["check_id"], severity=severity, usubjid=failure["usubjid"],
                           site_id=failure["site_id"], title=spec["description"], claims=claims, result=result, sim_date=day,
                           body_extra={**meta, "source": "template"})
        return Drafted(tmpl, fid, "template")
