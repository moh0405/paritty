from __future__ import annotations

from datetime import date

from psycopg import Connection

from app.hub.adapters.base import FeedAdapter
from app.hub.normalize import SubjectKey, parse_irt_ref, parse_lab_ref, parse_safety_ref


class LabVendorAdapter(FeedAdapter):
    system = "lab_vendor"

    def source_ids(self, conn: Connection, day: date) -> list[str]:
        return [r[0] for r in conn.execute("SELECT DISTINCT patient_ref FROM lab_vendor.transfer WHERE released AND file_date <= %s AND patient_ref IS NOT NULL", (day,))]

    def parse(self, source_id: str) -> SubjectKey | None:
        return parse_lab_ref(source_id)


class SafetyAdapter(FeedAdapter):
    system = "safety"

    def source_ids(self, conn: Connection, day: date) -> list[str]:
        return [r[0] for r in conn.execute("SELECT DISTINCT subject_ref FROM safety.case_versions WHERE available_on <= %s AND subject_ref IS NOT NULL", (day,))]

    def parse(self, source_id: str) -> SubjectKey | None:
        return parse_safety_ref(source_id)


class IrtAdapter(FeedAdapter):
    system = "irt"
    full_number = False

    def source_ids(self, conn: Connection, day: date) -> list[str]:
        return [r[0] for r in conn.execute("SELECT DISTINCT patient_ref FROM irt.kits WHERE dispensed <= %s AND patient_ref IS NOT NULL", (day,))]

    def parse(self, source_id: str) -> SubjectKey | None:
        return parse_irt_ref(source_id)


class CtmsAdapter(FeedAdapter):
    """Sites, not subjects: CTMS site records carry a code and a free-text name."""
    system = "ctms"
    entity = "site"

    def source_ids(self, conn: Connection, day: date) -> list[str]:
        return [r[0] for r in conn.execute("SELECT site_code FROM ctms.sites")]

    def parse(self, source_id: str):
        return None


ADAPTERS: dict[str, FeedAdapter] = {a.system: a for a in (LabVendorAdapter(), SafetyAdapter(), IrtAdapter(), CtmsAdapter())}
