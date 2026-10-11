"""CausalityAssessor (spec §9.5 'extra'): Gemini assesses with cited evidence; every claim is verified; low confidence, partial
verification or an unassessable case escalates to a person. Without Gemini the result is `unassessable` plus a verified fact worksheet:
a rule-based fallback would simply reproduce the reference labels the assessor is evaluated against."""
from __future__ import annotations

import json
from datetime import date, timedelta

from psycopg import Connection

from app.domain.enums import Role
from app.hub.crosswalk import SubjectMap
from app.llm import prompts
from app.llm.client import LLMClient, get_client
from app.llm.schemas import Citation, CausalityOut, Claim
from app.verification.checks import VerifyContext
from app.verification.sources import fetch_row
from app.verification.store import save_finding
from app.verification.verifier import Verifier

MIN_CONFIDENCE = 0.6
LIVER_TESTS = ("ALT", "AST", "ALP", "BILI", "CREAT", "HGB", "PLAT")
MAX_LAB_ROWS, MAX_CONMEDS = 12, 10


class CausalityAssessor:
    def __init__(self, conn: Connection, client: LLMClient | None = None):
        self.conn = conn
        self.client = client if client is not None else get_client()

    # ---- evidence -------------------------------------------------------------------------------------
    def _row(self, table: str, pk, drop: tuple[str, ...] = ()) -> dict | None:
        r = fetch_row(self.conn, table, str(pk))
        return None if r is None else {k: v for k, v in r.items() if k not in drop}

    def gather(self, case_id: str) -> dict | None:
        case = self.conn.execute("SELECT id, subject_ref, onset, reaction_term, version FROM safety.v_cases WHERE safetyreportid = %s ORDER BY version DESC LIMIT 1", (case_id,)).fetchone()
        if case is None:
            return None
        case_row_id, ref, onset, term, version = case
        usubjid = SubjectMap(self.conn).get("safety", ref)
        if not usubjid:
            return None
        ae = self.conn.execute("SELECT id FROM edc.ae WHERE usubjid = %s AND serious ORDER BY abs(onset_at - COALESCE(%s::date, onset_at)), id LIMIT 1", (usubjid, onset)).fetchone()
        rows: list[dict] = []

        def add(table: str, pk, drop: tuple[str, ...] = ()) -> None:
            r = self._row(table, pk, drop)
            if r is not None and not any(x["table"] == table and x["pk"] == str(pk) for x in rows):
                rows.append({"table": table, "pk": str(pk), "row": r})

        if ae:
            add("edc.ae", ae[0])
        add("edc.subjects", usubjid)
        add("safety.v_cases", case_row_id, drop=("narrative",))        # structured facts only; the free-text narrative is not needed and is not sent
        anchor = onset
        for (i,) in self.conn.execute("SELECT id FROM edc.exposure WHERE usubjid = %s ORDER BY start_at", (usubjid,)):
            add("edc.exposure", i)
        if anchor:
            for (i,) in self.conn.execute("SELECT id FROM edc.lab WHERE usubjid = %s AND test_code = ANY(%s) AND x_uln IS NOT NULL AND collected_at::date BETWEEN %s AND %s "
                                          "ORDER BY abs(collected_at::date - %s::date) LIMIT %s", (usubjid, list(LIVER_TESTS), anchor - timedelta(days=30), anchor + timedelta(days=30), anchor, MAX_LAB_ROWS)):
                add("edc.lab", i)
            for (i,) in self.conn.execute("SELECT id FROM edc.conmeds WHERE usubjid = %s AND start_at <= %s AND (end_at IS NULL OR end_at >= %s - 30) ORDER BY abs(start_at - %s::date) LIMIT %s",
                                          (usubjid, anchor + timedelta(days=30), anchor, anchor, MAX_CONMEDS)):
                add("edc.conmeds", i)
        for (i,) in self.conn.execute("SELECT id FROM edc.medical_history WHERE usubjid = %s ORDER BY id LIMIT 10", (usubjid,)):
            add("edc.medical_history", i)
        return {"usubjid": usubjid, "case_id": case_id, "rows": rows, "site_id": usubjid.split("-")[1], "ae_id": ae[0] if ae else None, "case_row_id": case_row_id}

    # ---- deterministic worksheet (facts, not a category) -----------------------------------------------------
    def worksheet(self, ev: dict) -> list[Claim]:
        by = {}
        for r in ev["rows"]:
            by.setdefault(r["table"], []).append(r)
        claims: list[Claim] = []

        def claim(table: str, r: dict, col: str, text: str) -> None:
            v = r["row"].get(col)
            claims.append(Claim(text=text.format(v=("missing" if v is None else str(v)[:10] if "date" in col or col.endswith("_at") else v)),
                                citations=[Citation(table=table, pk=r["pk"], column=col, value="" if v is None else str(v))]))

        if "edc.subjects" in by:
            claim("edc.subjects", by["edc.subjects"][0], "first_dose_at", "The subject's first dose was on {v}.")
        if "edc.ae" in by:
            claim("edc.ae", by["edc.ae"][0], "onset_at", "The event began on {v}.")
        ends = [r for r in by.get("edc.exposure", []) if r["row"].get("end_at")]
        if ends:
            last = max(ends, key=lambda r: r["row"]["end_at"])
            claim("edc.exposure", last, "end_at", "The latest recorded treatment period ended on {v}.")
        for r in by.get("edc.conmeds", [])[:3]:
            claim("edc.conmeds", r, "start_at", f"A concomitant medicine ({str(r['row'].get('term', '')).lower()}) started on " + "{v}.")
        return claims

    # ---- assessment -------------------------------------------------------------------------------------------
    def assess(self, case_id: str, day: date, trigger: str = "on_demand") -> dict | None:
        ev = self.gather(case_id)
        if ev is None:
            return None
        keys = {(r["table"], r["pk"]) for r in ev["rows"]}
        ctx = VerifyContext(self.conn, Role.MEDICAL_MONITOR, evidence=keys, rule_numbers={30.0})
        out: CausalityOut | None = None
        model = None
        try:
            version, prompt = prompts.render("causality", usubjid=ev["usubjid"], case_id=case_id, evidence_json=json.dumps(ev["rows"], default=str, indent=1))
            res = self.client.structured("causality", prompt, CausalityOut, model=None, prompt_version=version, conn=self.conn)
            out, model = (res.parsed, res.model) if res.parsed is not None else (None, None)
        except Exception as exc:
            print(f"warning: causality assessment fell back to the worksheet ({type(exc).__name__})")
        if out is not None:
            claims = out.evidence
            category, confidence, alt, model_escalate, source = out.category, max(0.0, min(1.0, out.confidence)), out.alternative_causes, out.escalate, "gemini"
        else:
            claims = self.worksheet(ev)
            category, confidence, alt, model_escalate, source = "unassessable", 0.0, [], True, "worksheet"
        result = Verifier().verify(claims, ctx) if claims else None
        status = result.status if result else "blocked"
        why = []
        if source == "worksheet":
            why.append("no AI assessment is available; the verified facts are listed for the medical monitor")
        if confidence < MIN_CONFIDENCE and source == "gemini":
            why.append(f"confidence {confidence:.2f} is below {MIN_CONFIDENCE}")
        if status != "verified" and source == "gemini":
            why.append(f"evidence verification is {status}")
        if category == "unassessable" and source == "gemini":
            why.append("the evidence is not enough to judge")
        if model_escalate and source == "gemini":
            why.append("the model flagged conflicting or thin evidence")
        escalate = bool(why)
        fid = save_finding(self.conn, module="causality", rule_id="causality_assessment", severity="high", usubjid=ev["usubjid"], site_id=ev["site_id"],
                           title=f"Causality assessment: {category}", claims=claims, result=result, sim_date=day,
                           body_extra={"case_id": case_id, "category": category, "source": source, "model": model, "trigger": trigger}) if result else None
        aid = str(self.conn.execute(
            "INSERT INTO ai.causality_assessments (case_id, usubjid, category, confidence, escalate, body, verification_status) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (case_id, ev["usubjid"], category, confidence, escalate, json.dumps({"alternative_causes": alt, "source": source, "model": model, "trigger": trigger,
                                                                                   "why_escalated": why, "finding_id": fid, "sim_date": str(day)}), status)).fetchone()[0])
        return {"id": aid, "case_id": case_id, "usubjid": ev["usubjid"], "category": category, "confidence": confidence, "escalate": escalate, "why": why,
                "alternative_causes": alt, "verification_status": status, "finding_id": fid, "source": source}

    def assess_conflicts(self, day: date, case_ids: list[str], limit: int = 5) -> int:
        """Assess cases whose causality conflicts between EDC and the safety database, once each."""
        done = {c for (c,) in self.conn.execute("SELECT case_id FROM ai.causality_assessments")}
        n = 0
        for cid in case_ids:
            if cid in done or n >= limit:
                continue
            done.add(cid)
            if self.assess(cid, day, "conflict"):
                n += 1
        return n
