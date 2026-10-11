"""Every state change writes to audit.log (spec §2 rule 8)."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from psycopg import Connection


def sim_ts(day: date) -> datetime:
    """Sim events are stamped on the sim calendar (noon UTC) so time-bucketed aggregates follow sim time."""
    return datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)


def audit(conn: Connection, sim_date: date | None, actor: str, action: str, entity: str, entity_id: str | None = None,
          payload: dict | None = None, role: str | None = None) -> None:
    conn.execute(
        "INSERT INTO audit.log (ts, sim_date, actor, role, action, entity, entity_id, payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (sim_ts(sim_date) if sim_date else datetime.now(timezone.utc), sim_date, actor, role, action, entity, entity_id,
         json.dumps(payload) if payload is not None else None))
