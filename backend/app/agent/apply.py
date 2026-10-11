"""What an approved agent action does in the simulation: the site's future query responses speed up by the action's factor."""
from __future__ import annotations

import json
from datetime import date

from psycopg import Connection

from app.audit.logger import audit


def response_factor(conn: Connection, site_id: str) -> float:
    r = conn.execute("SELECT value FROM ops.sim_state WHERE key = %s", (f"response_factor:{site_id}",)).fetchone()
    return float(r[0]) if r else 1.0


def apply_action(conn: Connection, draft_id: str, day: date, actor: str) -> dict | None:
    row = conn.execute("SELECT site_id, body FROM ops.drafts WHERE id = %s AND kind = 'agent_action'", (draft_id,)).fetchone()
    if row is None:
        return None
    site, body = row
    factor = min(response_factor(conn, site), float(body["factor"]))              # actions never undo each other
    conn.execute("INSERT INTO ops.sim_state (key, value) VALUES (%s, %s::jsonb) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (f"response_factor:{site}", json.dumps(factor)))
    audit(conn, day, actor, "agent.applied", "draft", draft_id, {"site": site, "action": body["action"], "factor": factor})
    return {"site_id": site, "factor": factor}
