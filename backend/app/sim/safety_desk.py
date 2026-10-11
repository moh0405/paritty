"""The simulated safety desk: when a site confirms its EDC data, the safety database issues a follow-up case version
(or opens the missing case). Part of the simulator, not of any detector."""
from __future__ import annotations

import json
import zlib
from datetime import date

from psycopg import Connection

from app.recon.sae.classifier import OUTCOME_E2B, edc_causality
from app.recon.sae.e2b_mapper import build_payload, e2b_date


def _latest(conn: Connection, case_id: str) -> tuple | None:
    return conn.execute("SELECT version, payload, subject_ref, causality, narrative FROM safety.case_versions "
                        "WHERE safetyreportid = %s ORDER BY version DESC LIMIT 1", (case_id,)).fetchone()


def issue_followup(conn: Connection, case_id: str, ae: dict, field: str, day: date) -> bool:
    """New version of `case_id` whose `field` agrees with the EDC AE `ae`. Effective the same day."""
    latest = _latest(conn, case_id)
    if latest is None:
        return False
    version, payload, subject_ref, causality, narrative = latest
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
    conn.execute("INSERT INTO safety.case_versions (safetyreportid, version, receivedate, subject_ref, payload, causality, narrative, available_on) "
                 "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                 (case_id, version + 1, payload["receivedate"], subject_ref, json.dumps(payload), causality,
                  (narrative or "") + " Follow-up: corrected after site query.", day))
    return True


def open_case(conn: Connection, ae_id: int, day: date) -> bool:
    """Create the missing case for an EDC serious AE."""
    ae = conn.execute("SELECT usubjid, term_coded, onset_at, end_at, outcome, causality FROM edc.ae WHERE id = %s", (ae_id,)).fetchone()
    if ae is None:
        return False
    usubjid, term, onset, end, outcome, causality = ae
    subj = conn.execute("SELECT age, sex, first_dose_at FROM edc.subjects WHERE usubjid = %s", (usubjid,)).fetchone()
    report_id = f"LS{zlib.crc32(f'ae{ae_id}'.encode()) % 90_000_000 + 10_000_000}"
    if conn.execute("SELECT 1 FROM safety.case_versions WHERE safetyreportid = %s", (report_id,)).fetchone():
        return False       # already opened for this AE
    payload = build_payload(report_id, day, {"term_coded": term, "onset_at": onset, "end_at": end, "outcome": outcome},
                            {"age": subj[0], "sex": subj[1], "first_dose_at": subj[2]})
    _, site, num = usubjid.split("-")
    conn.execute("INSERT INTO safety.case_versions (safetyreportid, version, receivedate, subject_ref, payload, causality, narrative, available_on) "
                 "VALUES (%s,1,%s,%s,%s,%s,%s,%s)",
                 (report_id, payload["receivedate"], f"SUBJ {num} / SITE {site}", json.dumps(payload), edc_causality(causality),
                  f"Case opened after site query: {term.lower()} with onset {onset}.", day))
    return True
