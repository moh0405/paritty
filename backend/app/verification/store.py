"""Persist findings, citations and verification results (spec §8 ai.*, §11)."""
from __future__ import annotations

import json
from datetime import date

from psycopg import Connection

from app.audit.logger import audit
from app.llm.schemas import Claim
from app.verification.verifier import VerificationResult


def save_finding(conn: Connection, *, module: str, rule_id: str, severity: str, usubjid: str | None, site_id: str | None,
                 title: str, claims: list[Claim], result: VerificationResult, sim_date: date | None,
                 body_extra: dict | None = None, run_ref: str | None = None) -> str:
    body = {"claims": [{"text": c.text, "status": r.status} for c, r in zip(claims, result.claims)], **(body_extra or {})}
    fid = str(conn.execute(
        "INSERT INTO ai.findings (run_ref, module, rule_id, severity, usubjid, site_id, title, body, verification_status, sim_date) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (run_ref, module, rule_id, severity, usubjid, site_id, title, json.dumps(body), result.status, sim_date)).fetchone()[0])
    for idx, (claim, res) in enumerate(zip(claims, result.claims)):
        for c in claim.citations:
            conn.execute("INSERT INTO ai.citations (finding_id, claim_idx, src_table, src_pk, src_column, cited_value, quote) "
                         "VALUES (%s,%s,%s,%s,%s,%s,%s)", (fid, idx, c.table, c.pk, c.column, c.value, c.quote))
        for r in res.checks:
            conn.execute("INSERT INTO ai.verifications (finding_id, claim_idx, check_name, passed, detail) VALUES (%s,%s,%s,%s,%s)",
                         (fid, idx, r.name, r.passed, r.detail))
    audit(conn, sim_date, "system", "finding.created", "finding", fid,
          {"module": module, "rule_id": rule_id, "status": result.status, "grounding_rate": round(result.grounding_rate, 3)})
    return fid
