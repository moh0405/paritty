"""Which tables a claim may cite, and how to fetch one cited row as JSON."""
from __future__ import annotations

from psycopg import Connection, sql

# table -> primary key column. Citations to anything else are rejected.
CITABLE: dict[str, str] = {
    "edc.subjects": "usubjid", "edc.ae": "id", "edc.lab": "id", "edc.vitals": "id", "edc.visits": "id",
    "edc.exposure": "id", "edc.conmeds": "id", "edc.medical_history": "id", "safety.v_cases": "id",
    "lab_vendor.transfer": "id", "safety.case_versions": "id", "ctms.sites": "site_code", "ctms.deviations": "id",
    "ctms.monitoring_visits": "id", "ctms.screening": "id", "irt.kits": "kit_no",
    "ai.protocol_chunks": "id", "ops.queries": "id", "ops.check_failures": "id",
}
INT_PK = {"id"}


def fetch_row(conn: Connection, table: str, pk: str) -> dict | None:
    """Row as a JSON-native dict, or None. Raises KeyError for a table that may not be cited."""
    if table not in CITABLE:
        raise KeyError(table)
    pk_col = CITABLE[table]
    schema, name = table.split(".")
    value = int(pk) if pk_col in INT_PK else pk
    row = conn.execute(
        sql.SQL("SELECT to_jsonb(t) FROM {}.{} t WHERE {} = %s").format(sql.Identifier(schema), sql.Identifier(name), sql.Identifier(pk_col)),
        (value,)).fetchone()
    return row[0] if row else None
