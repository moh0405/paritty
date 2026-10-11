"""Run active, approved checks on a ChangeSet and maintain ops.check_failures (spec §9.1 step 2)."""
from __future__ import annotations

import json
from datetime import date

from psycopg import Connection

from app.checks.base import EditCheckSpec, Failure
from app.checks.factory import CheckFactory, Compiled
from app.checks.library import LIBRARY
from app.recon.sae.specs import SAE_SPECS, is_sae_spec
from app.sim.ingestor import ChangeSet


def sync_library(conn: Connection) -> None:
    for s in [*LIBRARY, *SAE_SPECS]:
        conn.execute(
            "INSERT INTO ops.check_specs (id, type, params, ctq_category, severity, source, approval_status, rationale, active) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (s.id, s.type, json.dumps({**s.params, "_description": s.description}), s.ctq_category, s.severity, s.source,
             s.approval_status, json.dumps(s.rationale) if s.rationale else None, s.active))


def load_specs(conn: Connection, active_only: bool = True) -> list[EditCheckSpec]:
    rows = conn.execute("SELECT id, type, params, ctq_category, severity, source, approval_status, rationale, active "
                        "FROM ops.check_specs ORDER BY id").fetchall()
    out = []
    for id_, type_, params, ctq, sev, src, appr, rat, active in rows:
        desc = params.pop("_description", id_)
        spec = EditCheckSpec(id=id_, type=type_, params=params, description=desc, ctq_category=ctq, severity=sev,
                             source=src, approval_status=appr, rationale=rat, active=active)
        if not active_only or (active and appr == "approved"):
            out.append(spec)
    return out


class CheckRunner:
    def __init__(self, conn: Connection):
        self.conn = conn
        self.factory = CheckFactory()

    def run_all(self, changes: ChangeSet, day: date) -> dict[str, int]:
        """Returns {check_id: new_failures}. New = newly inserted or re-activated failure rows."""
        new_counts: dict[str, int] = {}
        for spec in load_specs(self.conn):
            if is_sae_spec(spec.params):
                continue          # detected by SaeReconciler
            compiled = self.factory.compile(spec)
            ids = None
            if compiled.incremental and not changes.full:
                ids = sorted(changes.touched(compiled.row_table))
                if not ids:
                    continue
            failures = compiled.run(self.conn, ids)
            new_counts[spec.id] = self._apply(spec.id, failures, ids, compiled, day)
        return new_counts

    def _apply(self, check_id: str, failures: list[Failure], ids: list[int] | None, compiled: Compiled, day: date) -> int:
        new = 0
        for f in failures:
            cur = self.conn.execute(
                "INSERT INTO ops.check_failures (check_id, usubjid, site_id, src_table, src_pk, observed, expected, detected_on) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (check_id, src_table, src_pk) DO UPDATE "
                "SET resolved_on = NULL, observed = EXCLUDED.observed WHERE ops.check_failures.resolved_on IS NOT NULL "
                "RETURNING id", (check_id, f.usubjid, f.site_id, f.src_table, f.src_pk, f.observed, f.expected, day))
            new += cur.rowcount
        current = [f.src_pk for f in failures]
        if ids is None:       # full run: anything unresolved and no longer failing is resolved
            self.conn.execute(
                "UPDATE ops.check_failures SET resolved_on = %s WHERE check_id = %s AND resolved_on IS NULL "
                "AND src_pk <> ALL(%s)", (day, check_id, current))
        else:                 # scoped run: only rows we re-examined can be resolved
            self.conn.execute(
                "UPDATE ops.check_failures SET resolved_on = %s WHERE check_id = %s AND resolved_on IS NULL "
                "AND src_pk = ANY(%s) AND src_pk <> ALL(%s)", (day, check_id, [str(i) for i in ids], current))
        return new
