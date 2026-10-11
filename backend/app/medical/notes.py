"""Review notes (spec §9.6): drafted from a subject's flagged findings, verified like every other claim, signed by a medical monitor."""
from __future__ import annotations

import json
from datetime import date, timedelta

from psycopg import Connection

from app.domain.enums import Role
from app.llm import prompts
from app.llm.client import LLMClient, get_client
from app.llm.schemas import Claim, ReviewNote
from app.medical.service import MedicalService
from app.verification.builders import build_claim
from app.verification.checks import VerifyContext
from app.verification.sources import fetch_row
from app.verification.store import save_finding
from app.verification.verifier import Verifier

CLOSING = " These findings are reasons to look and need medical review; no conclusion is drawn."
RULE_NUMBERS = {3.0, 2.0, 30.0, 7.0, 1.0, 0.001}
MAX_NEW_PER_DAY = 10


class NoteDrafter:
    def __init__(self, conn: Connection, client: LLMClient | None = None):
        self.conn = conn
        self.client = client if client is not None else get_client()

    def existing(self, usubjid: str) -> str | None:
        r = self.conn.execute("SELECT id FROM ops.drafts WHERE kind = 'note' AND subject_ref = %s AND state <> 'rejected' ORDER BY created_at LIMIT 1", (usubjid,)).fetchone()
        return str(r[0]) if r else None

    def draft(self, usubjid: str, day: date) -> str | None:
        if (e := self.existing(usubjid)):
            return e
        items = [i for i in MedicalService(self.conn).review_items(day) if i.usubjid == usubjid]
        if not items:
            return None
        site = items[0].site_id
        richest: dict[tuple[str, str], object] = {}
        for sp in (s for i in items for s in i.detail["claims"]):                 # one statement per source row: keep the one with the most detail
            key = (sp.table, sp.pk)
            if key not in richest or len(sp.columns) > len(richest[key].columns):
                richest[key] = sp
        specs = list(richest.values())
        rows = [{"table": s.table, "pk": s.pk, "row": fetch_row(self.conn, s.table, s.pk)} for s in specs]
        subj = fetch_row(self.conn, "edc.subjects", usubjid)
        if subj:
            rows.append({"table": "edc.subjects", "pk": usubjid, "row": {k: subj[k] for k in ("usubjid", "site_id", "age", "sex", "consent_at", "first_dose_at", "status")}})
        claims = [c for c in (build_claim(self.conn, s) for s in specs) if c]
        ctx = VerifyContext(self.conn, Role.MEDICAL_MONITOR, evidence={(r["table"], r["pk"]) for r in rows}, rule_numbers=RULE_NUMBERS)
        text, source, model = None, "template", None
        try:
            version, prompt = prompts.render("review_note", usubjid=usubjid, findings="\n".join(f"- {i.title}" for i in items),
                                             evidence_json=json.dumps(rows, default=str, indent=1))
            res = self.client.structured("review_note", prompt, ReviewNote, prompt_version=version, conn=self.conn)
            if res.parsed is not None:
                note: ReviewNote = res.parsed
                allc = [*note.claims, Claim(text=note.summary, citations=[c for cl in note.claims for c in cl.citations])]
                gv = Verifier().verify(allc, ctx)
                save_finding(self.conn, module="note_draft", rule_id="review_note", severity="medium", usubjid=usubjid, site_id=site, title="Review note draft",
                             claims=allc, result=gv, sim_date=day, body_extra={"source": "gemini", "model": res.model})
                if gv.status == "verified":
                    text, source, model = note.summary, "gemini", res.model
        except Exception as exc:
            print(f"warning: note drafting fell back to the template ({type(exc).__name__})")
        if text is None:
            text = f"Review note for {usubjid}: " + " ".join(c.text for c in claims) + CLOSING
        result = Verifier().verify(claims, ctx)
        fid = save_finding(self.conn, module="note", rule_id="review_note", severity="high", usubjid=usubjid, site_id=site, title=f"Review note: {usubjid}",
                           claims=claims, result=result, sim_date=day, body_extra={"source": source, "model": model, "note_text": text})
        body = {"text": text, "source": source, "finding_id": fid, "verification_status": result.status, "sim_date": str(day), "items": [i.title for i in items]}
        did = self.conn.execute("INSERT INTO ops.drafts (kind, subject_ref, site_id, body, state) VALUES ('note', %s, %s, %s, 'draft') RETURNING id", (usubjid, site, json.dumps(body))).fetchone()[0]
        return str(did)


def draft_for_flagged(conn: Connection, day: date, client: LLMClient | None = None) -> int:
    """A note draft for every subject with a critical or high finding that has none yet."""
    subjects = [u for (u,) in conn.execute(
        "SELECT DISTINCT f.usubjid FROM ai.findings f WHERE f.module = 'medical' AND f.usubjid IS NOT NULL AND f.severity IN ('critical','high') "
        "AND NOT EXISTS (SELECT 1 FROM ops.drafts d WHERE d.kind = 'note' AND d.subject_ref = f.usubjid AND d.state <> 'rejected') ORDER BY 1 LIMIT %s", (MAX_NEW_PER_DAY,))]
    drafter = NoteDrafter(conn, client)
    return sum(1 for u in subjects if drafter.draft(u, day))


def sign_due_notes(conn: Connection, day: date, actor: str = "sim:auto", after_days: int = 3) -> int:
    """Simulator only: the simulated medical monitor signs notes that have waited `after_days` simulated days (audit-logged as sim:auto)."""
    from app.audit.logger import audit
    rows = conn.execute("SELECT id FROM ops.drafts WHERE kind = 'note' AND state = 'draft' AND (body->>'sim_date')::date <= %s", (day - timedelta(days=after_days),)).fetchall()
    for (i,) in rows:
        conn.execute("UPDATE ops.drafts SET state = 'signed', approved_by = %s, approved_at = now() WHERE id = %s", (actor, i))
        audit(conn, day, actor, "draft.signed", "draft", str(i), {"kind": "note", "auto": True}, role=Role.MEDICAL_MONITOR.value)
    return len(rows)
