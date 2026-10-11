"""Lab trends by site and visit (spec §9.6): multiples of ULN over the visit schedule."""
from __future__ import annotations

from psycopg import Connection

TESTS = ("ALT", "AST", "ALP", "BILI", "CREAT", "HGB", "PLAT")
SQL = """
SELECT {key} AS k, v.visit, v.planned_day, count(*) AS n, avg(l.x_uln) AS mean, percentile_cont(0.9) WITHIN GROUP (ORDER BY l.x_uln) AS p90
FROM edc.lab l JOIN (SELECT usubjid, visit, max(planned_day) AS planned_day FROM edc.visits WHERE planned_day IS NOT NULL GROUP BY 1, 2) v USING (usubjid, visit)
WHERE l.test_code = %s AND l.x_uln IS NOT NULL AND v.visit NOT LIKE 'UNSCHEDULED%%' AND v.visit NOT LIKE 'AMBUL%%' AND v.visit <> 'RETRIEVAL'
GROUP BY 1, 2, 3 HAVING count(*) >= 3 ORDER BY 3, 1
"""


def lab_trends(conn: Connection, test: str, by: str) -> dict:
    if test not in TESTS:
        raise ValueError(f"test must be one of {', '.join(TESTS)}")
    if by not in ("site", "visit"):
        raise ValueError("by must be 'site' or 'visit'")
    pts = lambda sql_key: conn.execute(SQL.format(key=sql_key), (test,)).fetchall()  # noqa: E731
    study: dict[tuple, dict] = {}
    for _k, visit, day, n, mean, p90 in pts("'study'"):
        study[(visit, day)] = {"visit": visit, "planned_day": day, "n": n, "mean": round(float(mean), 3), "p90": round(float(p90), 3)}
    series: dict[str, list[dict]] = {"study": sorted(study.values(), key=lambda p: p["planned_day"])}
    if by == "site":
        for site, visit, day, n, mean, p90 in pts("l.site_id"):
            series.setdefault(site, []).append({"visit": visit, "planned_day": day, "n": n, "mean": round(float(mean), 3), "p90": round(float(p90), 3)})
    return {"test": test, "by": by, "series": [{"key": k, "points": v} for k, v in series.items()], "unit": "x ULN"}
