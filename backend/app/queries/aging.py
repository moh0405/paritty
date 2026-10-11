"""Query aging buckets by site (spec §9.3): 0-7, 8-14, 15-30, >30 days open as of sim today."""
from datetime import date

from psycopg import Connection

SQL = """
SELECT site_id,
  count(*) FILTER (WHERE age <= 7)                AS "0-7",
  count(*) FILTER (WHERE age BETWEEN 8 AND 14)    AS "8-14",
  count(*) FILTER (WHERE age BETWEEN 15 AND 30)   AS "15-30",
  count(*) FILTER (WHERE age > 30)                AS ">30",
  count(*)                                        AS open
FROM (SELECT site_id, (%(today)s::date - opened_on) AS age FROM ops.queries
      WHERE state IN ('Draft','Approved','Sent','Answered','Reopened')) q
GROUP BY site_id ORDER BY site_id
"""
BUCKETS = ["0-7", "8-14", "15-30", ">30"]


def aging_by_site(conn: Connection, today: date) -> list[dict]:
    cur = conn.execute(SQL, {"today": today})
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
