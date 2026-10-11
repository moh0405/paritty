"""Minimal E2B/openFDA-shaped payload builder for an EDC serious AE (the full mapper + mock safety API come in milestone 14)."""
from __future__ import annotations

from datetime import date

OUTCOME_E2B = {"RECOVERED/RESOLVED": "1", "RECOVERING/RESOLVING": "2", "NOT RECOVERED/NOT RESOLVED": "3",
               "RECOVERED/RESOLVED WITH SEQUELAE": "4", "FATAL": "5", "UNKNOWN": "6"}


def e2b_date(d) -> str | None:
    return None if d is None else d.strftime("%Y%m%d")


def build_payload(report_id: str, received: date, ae: dict, subject: dict) -> dict:
    fatal = ae["outcome"] == "FATAL"
    payload = {
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
    return payload
