"""E2B/openFDA-shaped safety messages built from an EDC serious AE (spec §9.5)."""
from __future__ import annotations

import zlib
from datetime import date

from psycopg import Connection

OUTCOME_E2B = {"RECOVERED/RESOLVED": "1", "RECOVERING/RESOLVING": "2", "NOT RECOVERED/NOT RESOLVED": "3",
               "RECOVERED/RESOLVED WITH SEQUELAE": "4", "FATAL": "5", "UNKNOWN": "6"}
CAUSALITY = {"PROBABLE": "Related", "POSSIBLE": "Related", "REMOTE": "Not related", "NONE": "Not related"}


def e2b_date(d) -> str | None:
    return None if d is None else d.strftime("%Y%m%d")


def build_payload(report_id: str, received: date, ae: dict, subject: dict) -> dict:
    fatal = ae["outcome"] == "FATAL"
    return {
        "safetyreportid": report_id, "receivedate": e2b_date(received), "serious": "1",
        **({"seriousnessdeath": "1"} if fatal else {}), "seriousnessother": "1",
        "patient": {
            "patientonsetage": str(int(subject["age"])) if subject.get("age") is not None else None,
            "patientsex": {"M": "1", "F": "2"}.get(subject.get("sex"), "0"),
            "reaction": [{"reactionmeddrapt": ae["term_coded"], "reactionmeddraversionpt": "27.0",
                          "reactionstartdate": e2b_date(ae["onset_at"]), "reactionenddate": e2b_date(ae.get("end_at")),
                          "reactionoutcome": OUTCOME_E2B.get(ae["outcome"] or "", "6")}],
            "drug": [{"medicinalproduct": "STUDY PATCH", "drugcharacterization": "1", "drugstartdate": e2b_date(subject.get("first_dose_at"))}]},
    }


class E2BMapper:
    """Builds the message an EDC integration would send to the safety database for a serious AE."""

    def __init__(self, conn: Connection):
        self.conn = conn

    @staticmethod
    def report_id(ae_id: int) -> str:
        return f"LS{zlib.crc32(f'ae{ae_id}'.encode()) % 90_000_000 + 10_000_000}"

    def message_for_ae(self, ae_id: int, day: date) -> dict | None:
        ae = self.conn.execute("SELECT usubjid, term_coded, onset_at, end_at, outcome, causality, serious FROM edc.ae WHERE id = %s", (ae_id,)).fetchone()
        if ae is None or not ae[6]:
            return None
        usubjid, term, onset, end, outcome, causality, _ = ae
        subj = self.conn.execute("SELECT age, sex, first_dose_at FROM edc.subjects WHERE usubjid = %s", (usubjid,)).fetchone()
        if subj is None:
            return None
        _, site, num = usubjid.split("-")
        payload = build_payload(self.report_id(ae_id), day, {"term_coded": term, "onset_at": onset, "end_at": end, "outcome": outcome},
                                {"age": subj[0], "sex": subj[1], "first_dose_at": subj[2]})
        return {"subject_ref": f"SUBJ {num} / SITE {site}", "version": 1, "causality": CAUSALITY.get(causality or ""), "available_on": str(day),
                "narrative": f"Case opened by EDC integration: {term.lower()} with onset {onset}.", "payload": payload}
