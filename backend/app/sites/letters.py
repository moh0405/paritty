"""Agenda and follow-up letter drafts for a site (spec §9.7): Gemini draft -> verify -> deterministic template fallback.
Drafts are stored in ops.drafts and change nothing until a person approves them; approval opens issues (sites/issues.py)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

from psycopg import Connection

from app.audit.logger import audit
from app.domain.enums import Role
from app.llm import prompts
from app.llm.client import LLMClient, get_client
from app.llm.schemas import Citation, Claim, FollowUpLetter, VisitAgenda
from app.sites.kris import KRI_DEFS
from app.sites.risk_model import ANOMALY_LABELS
from app.sites.visit_planner import action_for, site_level
from app.verification.checks import VerifyContext
from app.verification.store import save_finding
from app.verification.verifier import Verifier

VIEWER_ROLE = Role.CENTRAL_MONITOR
JOBS = {"agenda": ("visit_agenda", VisitAgenda), "letter": ("followup_letter", FollowUpLetter)}
KRI_TABLE, VISIT_TABLE = "ops.v_kri", "ctms.monitoring_visits"
DISCLAIMER = "These points are reasons to look at the data together; none of them is a conclusion about the site."
ACTION_WORDS = {"visit": "on-site visit", "call": "call", "remote": "remote review"}
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class NothingToRaise(Exception):
    """The site has no red or amber indicator, so there is nothing to put in an agenda or a letter."""


@dataclass
class Item:
    title: str                      # becomes the issue title when the draft is approved
    line: str                       # the sentence used in the template text
    claim: Claim | None = None      # None for a statistical pattern, which has no single source cell to cite


@dataclass
class SiteEvidence:
    site_id: str
    name: str | None
    day: date
    action: str
    items: list[Item] = field(default_factory=list)
    visit_line: str | None = None
    visit_claim: Claim | None = None
    rows: list[dict] = field(default_factory=list)          # what the model is shown
    glossary: dict[str, str] = field(default_factory=dict)  # kri code -> plain name and unit (wording help, not a citable cell)
    rule_numbers: set[float] = field(default_factory=set)   # numbers that belong to indicator names and the site number

    def keys(self) -> set[tuple[str, str]]:
        return {(r["table"], r["pk"]) for r in self.rows}

    def claims(self) -> list[Claim]:
        return [c for c in [*(i.claim for i in self.items), self.visit_claim] if c is not None]


def _cell(v) -> str:
    return "" if v is None else f"{v:g}" if isinstance(v, float) else str(v)


def gather(conn: Connection, site_id: str) -> SiteEvidence:
    row = conn.execute("SELECT r.sim_date, r.signals, s.name FROM ops.site_risk r LEFT JOIN hub.v_site_summary s USING (site_id) "
                       "WHERE r.site_id = %s ORDER BY r.sim_date DESC LIMIT 1", (site_id,)).fetchone()
    if row is None:
        raise LookupError(site_id)
    day, signals, name = row
    kris = conn.execute("SELECT ref, kri, value, comparator, rag FROM ops.v_kri WHERE sim_date = %s AND site_id = %s AND rag IN ('red','amber') "
                        "ORDER BY (rag = 'red') DESC, kri", (day, site_id)).fetchall()
    flagged = [a for a in signals.get("explanations", []) if a["kind"] == "anomaly"]
    reds = sum(r[4] == "red" for r in kris) + len(flagged)
    open_issues = conn.execute("SELECT count(*) FROM ops.issues WHERE site_id = %s AND status <> 'closed'", (site_id,)).fetchone()[0]
    ev = SiteEvidence(site_id, name, day, action_for(site_level(reds, len(kris) - sum(r[4] == "red" for r in kris)), open_issues) or "remote")
    ev.rule_numbers = {float(n) for n in _NUMBER.findall(site_id)}
    for ref, kri, value, comparator, rag in kris:
        d = KRI_DEFS[kri]
        ev.rule_numbers |= {float(n) for n in _NUMBER.findall(d["label"] + " " + d["unit"])}
        compared = f"; median across sites {comparator:.2f}" if comparator is not None else ""
        line = f"{d['label']}: {value:.2f} {d['unit']}{compared} ({rag})."
        cites = [Citation(table=KRI_TABLE, pk=ref, column="value", value=_cell(value)), Citation(table=KRI_TABLE, pk=ref, column="rag", value=rag)]
        if comparator is not None:
            cites.append(Citation(table=KRI_TABLE, pk=ref, column="comparator", value=_cell(comparator)))
        ev.items.append(Item(f"Review: {d['label']}", line, Claim(text=line, citations=cites)))
        # only real columns of the cited row: a model cites what it is shown, and a cited column that does not exist fails verification
        ev.rows.append({"table": KRI_TABLE, "pk": ref, "kri": kri, "value": value, "comparator": comparator, "rag": rag})
        ev.glossary[kri] = f"{d['label']} ({d['unit']})"
    for a in flagged:
        ev.items.append(Item(f"Review: {ANOMALY_LABELS.get(a['name'], a['name'])}", a["text"]))
    visit = conn.execute("SELECT m.id, m.visit_date, m.type FROM ctms.monitoring_visits m JOIN hub.v_ctms_sites c USING (site_code) "
                         "WHERE c.site_id = %s AND c.status <> 'rejected' AND m.visit_date <= (SELECT today FROM ops.sim_clock) "
                         "ORDER BY m.visit_date DESC LIMIT 1", (site_id,)).fetchone()
    if visit:
        ev.visit_line = f"Last monitoring visit on record: {visit[1]} ({visit[2]})."
        ev.visit_claim = Claim(text=ev.visit_line, citations=[Citation(table=VISIT_TABLE, pk=str(visit[0]), column="visit_date", value=str(visit[1])),
                                                              Citation(table=VISIT_TABLE, pk=str(visit[0]), column="type", value=visit[2])])
        ev.rows.append({"table": VISIT_TABLE, "pk": str(visit[0]), "visit_date": str(visit[1]), "type": visit[2]})
    return ev


def agenda_text(ev: SiteEvidence) -> str:
    points = "\n".join(f"{n}. {i.line}" for n, i in enumerate(ev.items, 1))
    return (f"Agenda for the {ACTION_WORDS[ev.action]} with site {ev.site_id}{f' ({ev.name})' if ev.name else ''} - data as of {ev.day}\n\n"
            f"Points to review with the site team:\n{points}\n\n{ev.visit_line or 'No monitoring visit on record yet.'}\n{DISCLAIMER}")


def letter_text(ev: SiteEvidence) -> str:
    points = "\n".join(f"- {i.line}" for i in ev.items)
    return (f"Dear site {ev.site_id} team,\n\nThank you for your continued work on the study. During routine central review of the data "
            f"(as of {ev.day}) we noted the following points that we would like to go through with you:\n{points}\n\n{DISCLAIMER} "
            f"Please reply with any context or corrections, and we will follow up with a {ACTION_WORDS[ev.action]}.\n\nKind regards,\nCentral monitoring")


TEMPLATES = {"agenda": agenda_text, "letter": letter_text}


class SiteDrafter:
    def __init__(self, conn: Connection, client: LLMClient | None = None):
        self.conn = conn
        self.client = client if client is not None else get_client()
        self.verifier = Verifier()

    def _ctx(self, ev: SiteEvidence) -> VerifyContext:
        return VerifyContext(self.conn, VIEWER_ROLE, evidence=ev.keys(), rule_numbers=ev.rule_numbers, rule_dates={str(ev.day)})

    def _save(self, ev: SiteEvidence, kind: str, claims: list[Claim], source: str, extra: dict) -> tuple[str, str]:
        result = self.verifier.verify(claims, self._ctx(ev))
        fid = save_finding(self.conn, module=f"site_{kind}", rule_id=f"site_{kind}", severity="medium", usubjid=None, site_id=ev.site_id,
                           title=f"Site {ev.site_id}: {kind} draft", claims=claims, result=result, sim_date=ev.day, body_extra={"source": source, **extra})
        return fid, result.status

    def _gemini(self, ev: SiteEvidence, kind: str) -> tuple[str, str] | None:
        job, schema = JOBS[kind]
        try:
            version, prompt = prompts.render(job, site=ev.site_id, action=ACTION_WORDS[ev.action], evidence_json=json.dumps(ev.rows, default=str, indent=1),
                                             indicators="\n".join(f"- {k}: {v}" for k, v in ev.glossary.items()))
            res = self.client.structured(job, prompt, schema, prompt_version=version, conn=self.conn)
        except Exception as exc:   # live API trouble must never block the monitor: the template still works
            print(f"warning: {kind} draft failed ({type(exc).__name__}: {exc}); using template")
            return None
        if res.parsed is None:
            return None
        citations = [c for cl in res.parsed.claims for c in cl.citations]
        claims = [*res.parsed.claims, Claim(text=res.parsed.text, citations=citations)]   # the text itself is checked
        fid, status = self._save(ev, kind, claims, "gemini", {"text": res.parsed.text, "model": res.model})
        return (res.parsed.text, fid) if status == "verified" else None

    def draft(self, site_id: str, kind: str, actor: str) -> dict:
        """Create (or return the pending) agenda or letter draft for a site. Nothing leaves the system until it is approved."""
        existing = self.conn.execute("SELECT id, body FROM ops.drafts WHERE kind = %s AND site_id = %s AND state = 'draft' ORDER BY created_at DESC LIMIT 1",
                                     (kind, site_id)).fetchone()
        if existing:
            return {"id": str(existing[0]), "kind": kind, "site_id": site_id, "state": "draft", "body": existing[1], "created": False}
        ev = gather(self.conn, site_id)
        if not ev.items:
            raise NothingToRaise(site_id)
        drafted = self._gemini(ev, kind)
        if drafted:
            text, fid, source = drafted[0], drafted[1], "gemini"
        else:
            fid, _ = self._save(ev, kind, ev.claims(), "template", {})
            text, source = TEMPLATES[kind](ev), "template"
        body = {"text": text, "items": [{"title": i.title, "detail": i.line} for i in ev.items], "action": ev.action, "finding_id": fid,
                "source": source, "as_of": str(ev.day)}
        did = str(self.conn.execute("INSERT INTO ops.drafts (kind, site_id, body, state) VALUES (%s,%s,%s,'draft') RETURNING id",
                                    (kind, site_id, json.dumps(body))).fetchone()[0])
        audit(self.conn, ev.day, actor, "draft.created", "draft", did, {"kind": kind, "site_id": site_id, "source": source, "finding_id": fid})
        return {"id": did, "kind": kind, "site_id": site_id, "state": "draft", "body": body, "created": True}
