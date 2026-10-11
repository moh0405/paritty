"""Move staged rows into edc.* once their entry date has arrived (spec §9.1 step 1)."""
from datetime import date

from psycopg import Connection, sql

# (table, has_entered_at). medical_history has no entry date: it follows its subject.
TABLES = ["sites", "subjects", "ae", "lab", "vitals", "visits", "exposure", "conmeds"]


def release_through(conn: Connection, day: date) -> dict[str, int]:
    """Release pending rows with entered_at <= day; apply due subject updates. Returns rows moved per table."""
    moved: dict[str, int] = {}
    for t in TABLES:
        ident = sql.Identifier
        if t == "sites":
            q = sql.SQL("INSERT INTO edc.sites SELECT * FROM edc_pending.sites ON CONFLICT DO NOTHING")
            cur = conn.execute(q)
            conn.execute("DELETE FROM edc_pending.sites")
        else:
            q = sql.SQL(
                "WITH m AS (DELETE FROM edc_pending.{t} WHERE entered_at <= %s RETURNING *) "
                "INSERT INTO edc.{t} SELECT * FROM m"
            ).format(t=ident(t))
            cur = conn.execute(q, (day,))
        moved[t] = cur.rowcount
    cur = conn.execute(
        "WITH m AS (DELETE FROM edc_pending.medical_history h USING edc.subjects s "
        "WHERE h.usubjid = s.usubjid RETURNING h.*) INSERT INTO edc.medical_history SELECT * FROM m"
    )
    moved["medical_history"] = cur.rowcount
    cur = conn.execute(
        "UPDATE edc.subjects s SET status = u.status, discontinued_at = COALESCE(u.discontinued_at, s.discontinued_at), "
        "death_at = COALESCE(u.death_at, s.death_at) FROM edc_pending.subject_updates u "
        "WHERE u.usubjid = s.usubjid AND u.apply_on <= %s AND NOT u.applied", (day,))
    moved["subject_updates"] = cur.rowcount
    conn.execute("UPDATE edc_pending.subject_updates SET applied = true WHERE apply_on <= %s AND NOT applied "
                 "AND usubjid IN (SELECT usubjid FROM edc.subjects)", (day,))
    return moved
