"""Data catalog (spec §9.9): descriptions, owners, freshness, BM25 search."""
from __future__ import annotations

from datetime import date, datetime, timezone

from psycopg import Connection

FRESHNESS: dict[str, str] = {
    "edc.subjects": "SELECT max(entered_at) FROM edc.subjects", "edc.ae": "SELECT max(entered_at) FROM edc.ae", "edc.lab": "SELECT max(entered_at) FROM edc.lab",
    "edc.vitals": "SELECT max(entered_at) FROM edc.vitals", "edc.visits": "SELECT max(entered_at) FROM edc.visits",
    "edc.exposure": "SELECT max(entered_at) FROM edc.exposure", "edc.conmeds": "SELECT max(entered_at) FROM edc.conmeds",
    "lab_vendor.transfer": "SELECT max(file_date) FROM lab_vendor.transfer WHERE released",
    "safety.case_versions": "SELECT max(available_on) FROM safety.case_versions WHERE available_on <= %(t)s",
    "irt.kits": "SELECT max(dispensed) FROM irt.kits WHERE dispensed <= %(t)s",
    "ctms.monitoring_visits": "SELECT max(visit_date) FROM ctms.monitoring_visits WHERE visit_date BETWEEN DATE '2000-01-01' AND %(t)s",
    "ctms.deviations": "SELECT max(occurred) FROM ctms.deviations WHERE occurred BETWEEN DATE '2000-01-01' AND %(t)s",
    "ctms.screening": "SELECT max(screened) FROM ctms.screening WHERE screened <= %(t)s",
    "ops.queries": "SELECT max(opened_on) FROM ops.queries", "ops.kri_values": "SELECT max(sim_date) FROM ops.kri_values",
    "ops.lock_forecasts": "SELECT max(sim_date) FROM ops.lock_forecasts",
}


def noon(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc)


def refresh(conn: Connection, day: date) -> int:
    n = 0
    for (table,) in conn.execute("SELECT table_name FROM hub.catalog").fetchall():
        count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        newest = conn.execute(FRESHNESS[table], {"t": day}).fetchone()[0] if table in FRESHNESS else day
        conn.execute("UPDATE hub.catalog SET row_count = %s, last_loaded = %s WHERE table_name = %s", (count, noon(newest) if newest else None, table))
        n += 1
    return n


def search(conn: Connection, q: str | None, day: date, limit: int = 50) -> list[dict]:
    cols = "table_name, description, owner, refresh, sensitivity, last_loaded, row_count"
    if q and q.strip():
        try:
            with conn.transaction():
                rows = conn.execute(f"SELECT {cols} FROM hub.catalog ORDER BY description <@> to_bm25query(%s, 'hub.catalog_bm25') LIMIT %s", (q, limit)).fetchall()
            rows = [r for r in rows if _matches(q, r)] or rows[:0]
        except Exception:
            rows = []
        if not rows:       # BM25 unavailable, or only a table-name fragment was typed
            like = f"%{q.strip()}%"
            rows = conn.execute(f"SELECT {cols} FROM hub.catalog WHERE table_name ILIKE %s OR description ILIKE %s ORDER BY table_name LIMIT %s", (like, like, limit)).fetchall()
    else:
        rows = conn.execute(f"SELECT {cols} FROM hub.catalog ORDER BY table_name LIMIT %s", (limit,)).fetchall()
    return [{"table_name": r[0], "description": r[1], "owner": r[2], "refresh": r[3], "sensitivity": r[4], "last_loaded": r[5], "row_count": r[6],
             "age_days": (day - r[5].date()).days if r[5] else None} for r in rows]


def _matches(q: str, row) -> bool:
    words = [w.lower() for w in q.split() if len(w) > 2]
    text = f"{row[0]} {row[1]}".lower()
    return any(w in text for w in words) if words else True
