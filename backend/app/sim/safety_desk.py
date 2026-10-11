"""The simulated safety desk: when a site confirms its EDC data, the safety database issues a follow-up case version
(or opens the missing case). Part of the simulator, not of any detector."""
from __future__ import annotations

import json
import zlib
from datetime import date

from psycopg import Connection

from app.recon.sae import mock_safety_api
from app.recon.sae.classifier import OUTCOME_E2B, edc_causality
from app.recon.sae.e2b_mapper import E2BMapper, e2b_date


def _latest(conn: Connection, case_id: str) -> tuple | None:
    """(version, payload, subject_ref, causality, narrative, in_inbox) of the newest version, wherever the case lives."""
    r = conn.execute("SELECT version, payload, subject_ref, causality, narrative FROM safety.case_versions WHERE safetyreportid = %s ORDER BY version DESC LIMIT 1", (case_id,)).fetchone()
    m = conn.execute("SELECT message FROM mock_safety.inbox WHERE status = 'received' AND message->'payload'->>'safetyreportid' = %s ORDER BY COALESCE((message->>'version')::int, 1) DESC LIMIT 1", (case_id,)).fetchone()
    if m and (r is None or int(m[0].get("version") or 1) > r[0]):
        msg = m[0]
        return int(msg.get("version") or 1), msg["payload"], msg["subject_ref"], msg.get("causality"), msg.get("narrative"), True
    return (*r, False) if r else None


def issue_followup(conn: Connection, case_id: str, ae: dict, field: str, day: date) -> bool:
    """New version of `case_id` whose `field` agrees with the EDC AE `ae`. Effective the same day."""
    latest = _latest(conn, case_id)
    if latest is None:
        return False
    version, payload, subject_ref, causality, narrative, in_inbox = latest
    payload = json.loads(json.dumps(payload))
    rx = payload["patient"]["reaction"][0]
    if field == "onset":
        rx["reactionstartdate"] = e2b_date(ae["onset_at"])
    elif field == "term":
        rx["reactionmeddrapt"] = ae["term_coded"]
    elif field == "seriousness":
        payload["serious"] = "1" if ae["serious"] else "2"
        payload.setdefault("seriousnessother", "1")
    elif field == "causality":
        causality = edc_causality(ae["causality"])
    elif field in ("outcome", "death"):
        rx["reactionoutcome"] = OUTCOME_E2B.get(ae["outcome"] or "", "6")
        payload.pop("seriousnessdeath", None)
        if ae["outcome"] == "FATAL":
            payload["seriousnessdeath"] = "1"
    payload["receivedate"] = e2b_date(day)
    narrative = (narrative or "") + " Follow-up: corrected after site query."
    if in_inbox:         # the case arrived through the mock safety API: the follow-up goes the same way, as a new version
        return mock_safety_api.submit(conn, {"subject_ref": subject_ref, "version": version + 1, "causality": causality, "narrative": narrative,
                                             "available_on": str(day), "payload": payload}, None, day)["status"] == "received"
    conn.execute("INSERT INTO safety.case_versions (safetyreportid, version, receivedate, subject_ref, payload, causality, narrative, available_on) "
                 "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (case_id, version + 1, payload["receivedate"], subject_ref, json.dumps(payload), causality, narrative, day))
    return True


def open_case(conn: Connection, ae_id: int, day: date) -> bool:
    """Open the missing case: the EDC integration sends an E2B message to the mock safety API (the inbox)."""
    msg = E2BMapper(conn).message_for_ae(ae_id, day)
    if msg is None:
        return False
    if mock_safety_api.latest_version(conn, msg["payload"]["safetyreportid"]):
        return False       # already opened for this AE
    return mock_safety_api.submit(conn, msg, ae_id, day)["status"] == "received"
