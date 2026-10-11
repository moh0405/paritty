"""A mock safety-database intake (spec §9.5): validates E2B-shaped messages and stores them in mock_safety.inbox."""
from __future__ import annotations

import json
from datetime import date

from psycopg import Connection

REQUIRED_TOP = ("subject_ref", "payload")
REQUIRED_PAYLOAD = ("safetyreportid", "receivedate", "serious", "patient")


def validate(message: dict) -> list[str]:
    errors = [f"missing {k}" for k in REQUIRED_TOP if not message.get(k)]
    p = message.get("payload") or {}
    errors += [f"payload is missing {k}" for k in REQUIRED_PAYLOAD if not p.get(k)]
    rx = ((p.get("patient") or {}).get("reaction") or [{}])[0]
    if not rx.get("reactionmeddrapt"):
        errors.append("payload.patient.reaction[0].reactionmeddrapt is required")
    if p.get("serious") not in ("1", "2"):
        errors.append("payload.serious must be '1' (serious) or '2'")
    if rx.get("reactionstartdate") and (len(str(rx["reactionstartdate"])) != 8 or not str(rx["reactionstartdate"]).isdigit()):
        errors.append("reactionstartdate must be YYYYMMDD")
    return errors


def submit(conn: Connection, message: dict, source_ae_id: int | None, day: date) -> dict:
    """Store the message. Rejected messages are kept (status 'rejected') with their reasons so intake problems are visible."""
    errors = validate(message)
    sid, version = ((message.get("payload") or {}).get("safetyreportid"), int(message.get("version") or 1))
    if not errors and sid:
        clash = conn.execute("SELECT 1 FROM mock_safety.inbox WHERE status = 'received' AND message->'payload'->>'safetyreportid' = %s AND COALESCE((message->>'version')::int, 1) = %s",
                             (sid, version)).fetchone() or conn.execute("SELECT 1 FROM safety.case_versions WHERE safetyreportid = %s AND version = %s", (sid, version)).fetchone()
        if clash:
            errors.append(f"case {sid} version {version} already exists")
    message = {**message, "available_on": message.get("available_on") or str(day)}
    status = "rejected" if errors else "received"
    row = conn.execute("INSERT INTO mock_safety.inbox (message, source_ae_id, status) VALUES (%s,%s,%s) RETURNING id", (json.dumps({**message, "errors": errors} if errors else message), source_ae_id, status)).fetchone()
    return {"id": row[0], "status": status, "safetyreportid": sid, "errors": errors}


def latest_version(conn: Connection, case_id: str) -> int:
    return conn.execute("SELECT COALESCE(max(version), 0) FROM safety.v_cases WHERE safetyreportid = %s", (case_id,)).fetchone()[0]
