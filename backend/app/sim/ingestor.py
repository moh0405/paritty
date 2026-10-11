"""Move staged rows into edc.* once their entry date has arrived (spec §9.1 step 1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from psycopg import Connection, sql

ROW_TABLES = ["ae", "lab", "vitals", "visits", "exposure", "conmeds"]


@dataclass
class ChangeSet:
    """Row ids inserted or updated during one daily cycle, per edc table. `full=True` means 'treat everything as new'."""
    inserted: dict[str, set[int]] = field(default_factory=dict)
    updated: dict[str, set[int]] = field(default_factory=dict)
    full: bool = False

    def touched(self, table: str) -> set[int]:
        return self.inserted.get(table, set()) | self.updated.get(table, set())

    def mark_updated(self, table: str, row_id: int) -> None:
        self.updated.setdefault(table, set()).add(row_id)

    def mark_inserted(self, table: str, row_id: int) -> None:
        self.inserted.setdefault(table, set()).add(row_id)


def release_through(conn: Connection, day: date) -> tuple[dict[str, int], ChangeSet]:
    """Release pending rows with entered_at <= day; apply due subject updates; release due vendor files."""
    moved: dict[str, int] = {}
    changes = ChangeSet()
    cur = conn.execute("INSERT INTO edc.sites SELECT * FROM edc_pending.sites ON CONFLICT DO NOTHING")
    conn.execute("DELETE FROM edc_pending.sites")
    cur = conn.execute("WITH m AS (DELETE FROM edc_pending.subjects WHERE entered_at <= %s RETURNING *) "
                       "INSERT INTO edc.subjects SELECT * FROM m", (day,))
    moved["subjects"] = cur.rowcount
    for t in ROW_TABLES:
        q = sql.SQL("WITH m AS (DELETE FROM edc_pending.{t} WHERE entered_at <= %s RETURNING *) "
                    "INSERT INTO edc.{t} SELECT * FROM m RETURNING id").format(t=sql.Identifier(t))
        rows = conn.execute(q, (day,)).fetchall()
        moved[t] = len(rows)
        if rows:
            changes.inserted[t] = {r[0] for r in rows}
    moved["medical_history"] = conn.execute(
        "WITH m AS (DELETE FROM edc_pending.medical_history h USING edc.subjects s WHERE h.usubjid = s.usubjid RETURNING h.*) "
        "INSERT INTO edc.medical_history SELECT * FROM m").rowcount
    moved["subject_updates"] = conn.execute(
        "UPDATE edc.subjects s SET status = u.status, discontinued_at = COALESCE(u.discontinued_at, s.discontinued_at), "
        "death_at = COALESCE(u.death_at, s.death_at) FROM edc_pending.subject_updates u "
        "WHERE u.usubjid = s.usubjid AND u.apply_on <= %s AND NOT u.applied", (day,)).rowcount
    conn.execute("UPDATE edc_pending.subject_updates SET applied = true WHERE apply_on <= %s AND NOT applied "
                 "AND usubjid IN (SELECT usubjid FROM edc.subjects)", (day,))
    moved["lab_vendor_files"] = conn.execute(
        "UPDATE lab_vendor.transfer SET released = true WHERE NOT released AND file_date <= %s", (day,)).rowcount
    return moved, changes
