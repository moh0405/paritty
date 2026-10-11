"""Lineage (spec §9.9): the trail from any finding, query or failure back to the source rows and the rule that produced it."""
from __future__ import annotations

from psycopg import Connection


def _steps_for_failure(conn: Connection, fid: int) -> list[dict]:
    f = conn.execute("SELECT check_id, usubjid, site_id, src_table, src_pk, observed, expected, detected_on, resolved_on FROM ops.check_failures WHERE id = %s", (fid,)).fetchone()
    if f is None:
        return []
    spec = conn.execute("SELECT type, severity, ctq_category, params->>'_description' FROM ops.check_specs WHERE id = %s", (f[0],)).fetchone()
    return [{"label": "Source row", "table": f[3], "pk": f[4], "detail": f"subject {f[1]}, site {f[2]}"},
            {"label": "Rule that fired", "table": "ops.check_specs", "pk": f[0], "detail": f"{spec[3]} ({spec[0]}, {spec[1]}, {spec[2]})" if spec else f[0]},
            {"label": "Failure recorded", "table": "ops.check_failures", "pk": str(fid), "detail": f"observed {f[5]}; expected {f[6]}; detected {f[7]}" + (f"; resolved {f[8]}" if f[8] else "")}]


def trail(conn: Connection, entity: str, entity_id: str) -> dict:
    steps: list[dict] = []
    if entity == "failure":
        steps = _steps_for_failure(conn, int(entity_id))
    elif entity == "query":
        q = conn.execute("SELECT failure_id, finding_id, state, opened_on, closed_on, closed_reason FROM ops.queries WHERE id = %s", (entity_id,)).fetchone()
        if q is None:
            return {"entity": entity, "id": entity_id, "steps": []}
        if q[0]:
            steps += _steps_for_failure(conn, q[0])
        if q[1]:
            steps.append({"label": "Evidence finding", "table": "ai.findings", "pk": str(q[1]), "detail": "claims and citations are listed under this finding"})
        steps.append({"label": "Query", "table": "ops.queries", "pk": entity_id, "detail": f"{q[2]}; opened {q[3]}" + (f"; closed {q[4]} ({q[5]})" if q[4] else "")})
        for ev, actor, day in conn.execute("SELECT event, actor, sim_date FROM ops.query_events WHERE query_id = %s ORDER BY ts, event", (entity_id,)):
            steps.append({"label": f"Event: {ev}", "table": "ops.query_events", "pk": entity_id, "detail": f"{day} by {actor}"})
    elif entity == "finding":
        f = conn.execute("SELECT module, rule_id, title, verification_status, body->'rule' FROM ai.findings WHERE id = %s", (entity_id,)).fetchone()
        if f is None:
            return {"entity": entity, "id": entity_id, "steps": []}
        steps.append({"label": "Finding", "table": "ai.findings", "pk": entity_id, "detail": f"{f[0]} / {f[1]}: {f[2]} ({f[3]})"})
        if f[4]:
            steps.append({"label": "Rule", "table": "rule", "pk": f[1], "detail": str(f[4])})
        for t, pk, col, val in conn.execute("SELECT src_table, src_pk, src_column, cited_value FROM ai.citations WHERE finding_id = %s ORDER BY id", (entity_id,)):
            steps.append({"label": "Cited cell", "table": t, "pk": pk, "detail": f"{col} = {val}"})
    return {"entity": entity, "id": entity_id, "steps": steps}
