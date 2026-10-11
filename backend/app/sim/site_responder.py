"""SiteResponder (spec §9.1): when a query is Sent, schedule a response by site personality and later apply it.
Kinds: `correct` (fix the value so the check passes), `explain` (no data change), `wrong_correction` (changes data, check still fails)."""
from __future__ import annotations

import json
import math
import zlib
from datetime import date, timedelta

import numpy as np
from psycopg import Connection

from app.sim.corrections import EXPLAIN_ONLY, FIXERS
from app.sim.ingestor import ChangeSet
from app.sim.world import WorldModel

EXPLAIN_RATE = 0.08
SIGMA = 0.6


class SiteResponder:
    def __init__(self, conn: Connection, world: WorldModel, sim_seed: int):
        self.conn, self.world, self.seed = conn, world, sim_seed

    @staticmethod
    def key(check_id: str, src_table: str, src_pk: str, reopen_count: int) -> int:
        """Stable identity of a query across runs (query UUIDs are random, so they must not seed anything)."""
        return zlib.crc32(f"{check_id}|{src_table}|{src_pk}|{reopen_count}".encode())

    def _rng(self, day: date, key: int, salt: int = 0) -> np.random.Generator:
        return np.random.default_rng([self.seed, day.toordinal(), key, salt])

    def schedule(self, query_id: str, site_id: str, check_id: str, day: date, key: int) -> None:
        p = self.world.params(site_id)
        r = self._rng(day, key)
        mu = math.log(p.response_mean_days) - SIGMA ** 2 / 2
        delay = max(1, int(round(r.lognormal(mu, SIGMA))))
        u = r.random()
        if check_id in EXPLAIN_ONLY or check_id not in FIXERS:
            kind = "explain"
        elif u < p.wrong_correction_rate:
            kind = "wrong_correction"
        elif u < p.wrong_correction_rate + EXPLAIN_RATE:
            kind = "explain"
        else:
            kind = "correct"
        self.conn.execute("INSERT INTO ops.site_responses (query_id, due_on, kind, payload) VALUES (%s,%s,%s,%s)",
                          (query_id, day + timedelta(days=delay), kind, json.dumps({"check_id": check_id})))

    def deliver(self, day: date, changes: ChangeSet) -> list[tuple[str, str]]:
        """Apply responses due today (or earlier). Returns [(query_id, kind)] for queries now ready to be marked Answered."""
        due = self.conn.execute(
            "SELECT r.id, r.query_id, r.kind, r.payload->>'check_id', f.src_table, f.src_pk, f.observed, q.reopen_count, f.expected, f.usubjid FROM ops.site_responses r "
            "JOIN ops.queries q ON q.id = r.query_id JOIN ops.check_failures f ON f.id = q.failure_id "
            "WHERE NOT r.delivered AND r.due_on <= %s AND q.state = 'Sent' ORDER BY r.id", (day,)).fetchall()
        out = []
        for rid, qid, kind, check_id, src_table, src_pk, observed, reopens, expected, usubjid in due:
            if kind != "explain":
                fixer = FIXERS.get(check_id)
                if fixer:
                    r = self._rng(day, self.key(check_id, src_table, src_pk, reopens), salt=1)
                    fixer(self.conn, {"src_table": src_table, "src_pk": src_pk, "observed": observed, "expected": expected, "usubjid": usubjid, "check_id_hint": check_id}, changes, day,
                          kind == "wrong_correction", r)
            self.conn.execute("UPDATE ops.site_responses SET delivered = true WHERE id = %s", (rid,))
            out.append((str(qid), kind))
        return out
