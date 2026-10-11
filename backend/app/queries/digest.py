"""MinorIssueDigest (spec §9.3): queries with priority < 0.15 are grouped weekly per site into one digest the data manager approves together."""
from __future__ import annotations

from datetime import date, timedelta

from psycopg import Connection

from app.audit.logger import audit
from app.queries import lifecycle as lc

MINOR_PRIORITY = 0.15
MAX_LINES = 40


def week_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


class MinorIssueDigest:
    def __init__(self, conn: Connection):
        self.conn = conn

    def build_weekly(self, day: date) -> list[str]:
        rows = self.conn.execute(
            "SELECT q.id, q.site_id, q.usubjid, coalesce(s.params->>'_description', f.check_id) FROM ops.queries q JOIN ops.check_failures f ON f.id = q.failure_id "
            "JOIN ops.check_specs s ON s.id = f.check_id WHERE q.state = 'Draft' AND q.priority < %s "
            "AND NOT EXISTS (SELECT 1 FROM ops.digests d WHERE q.id = ANY(d.query_ids)) ORDER BY q.site_id, f.id", (MINOR_PRIORITY,)).fetchall()
        by_site: dict[str, list[tuple]] = {}
        for r in rows:
            by_site.setdefault(r[1], []).append(r)
        made = []
        for site, items in by_site.items():
            lines = [f"- {u}: {d}" for _q, _s, u, d in items[:MAX_LINES]]
            more = f"\n(and {len(items) - MAX_LINES} more)" if len(items) > MAX_LINES else ""
            text = (f"Weekly summary of {len(items)} minor data issue(s) for site {site}. None is urgent; please review and correct or explain each at your next convenience.\n"
                    + "\n".join(lines) + more)
            did = self.conn.execute("INSERT INTO ops.digests (site_id, week_of, query_ids, text, state) VALUES (%s,%s,%s,%s,'Draft') RETURNING id",
                                    (site, week_of(day), [i[0] for i in items], text)).fetchone()[0]
            audit(self.conn, day, "system", "digest.drafted", "digest", str(did), {"site": site, "queries": len(items)})
            made.append(str(did))
        return made

    def approve(self, digest_id: str, actor: str, day: date) -> int:
        row = self.conn.execute("SELECT query_ids, state FROM ops.digests WHERE id = %s FOR UPDATE", (digest_id,)).fetchone()
        if row is None:
            raise KeyError(digest_id)
        if row[1] != "Draft":
            raise lc.IllegalTransition(f"digest is already {row[1]}")
        n = 0
        for qid in row[0]:
            if self.conn.execute("SELECT state FROM ops.queries WHERE id = %s", (qid,)).fetchone()[0] == lc.DRAFT:
                lc.transition(lc.Ctx(self.conn, str(qid), day, actor, {"digest": digest_id}), "approve")
                n += 1
        self.conn.execute("UPDATE ops.digests SET state = 'Approved' WHERE id = %s", (digest_id,))
        audit(self.conn, day, actor, "digest.approved", "digest", digest_id, {"queries": n})
        return n
