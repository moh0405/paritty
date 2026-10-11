"""Site issue tracking (spec §9.7): every approved agenda item or letter opens an issue that stays open until someone closes it."""
from __future__ import annotations

import json
from datetime import date

from psycopg import Connection

from app.audit.logger import audit

OPEN, IN_PROGRESS, CLOSED = "open", "in_progress", "closed"
STATUSES = (OPEN, IN_PROGRESS, CLOSED)
ISSUE_KINDS = ("agenda", "letter")       # draft kinds whose approval opens issues
COLUMNS = "id, site_id, source, title, status, owner, opened, closed, links"


def _rows(cur) -> list[dict]:
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def open_issue(conn: Connection, *, site_id: str, source: str, title: str, owner: str, day: date, links: dict, actor: str) -> str | None:
    """Returns the new issue id, or None when the same issue is already open at the site."""
    if conn.execute("SELECT 1 FROM ops.issues WHERE site_id = %s AND title = %s AND status <> %s", (site_id, title, CLOSED)).fetchone():
        return None
    iid = str(conn.execute("INSERT INTO ops.issues (site_id, source, title, status, owner, opened, links) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                           (site_id, source, title, OPEN, owner, day, json.dumps(links))).fetchone()[0])
    audit(conn, day, actor, "issue.opened", "issue", iid, {"site_id": site_id, "source": source, "title": title})
    return iid


def open_from_draft(conn: Connection, draft_id: str, day: date, actor: str) -> list[str]:
    """Called when a human approves an agenda or a letter: one issue per agenda item, one follow-up issue per letter."""
    row = conn.execute("SELECT kind, site_id, body FROM ops.drafts WHERE id = %s", (draft_id,)).fetchone()
    if row is None or row[0] not in ISSUE_KINDS or row[1] is None:
        return []
    kind, site, body = row
    links = {"draft_id": draft_id, "finding_id": body.get("finding_id")}
    titles = [i["title"] for i in body.get("items", [])] if kind == "agenda" else ["Follow-up letter sent: response from the site awaited"]
    made = [open_issue(conn, site_id=site, source=kind, title=t, owner=actor, day=day, links=links, actor=actor) for t in titles]
    return [i for i in made if i]


def list_issues(conn: Connection, status: str | None = None, site_id: str | None = None, scope: str | None = None) -> list[dict]:
    return _rows(conn.execute(
        f"SELECT {COLUMNS} FROM ops.issues WHERE (%(status)s::text IS NULL OR status = %(status)s) AND (%(site)s::text IS NULL OR site_id = %(site)s) "
        "AND (%(scope)s::text IS NULL OR site_id = ANY(string_to_array(%(scope)s, ','))) ORDER BY (status = 'closed'), opened DESC, title",
        {"status": status, "site": site_id, "scope": scope}))


def update_issue(conn: Connection, issue_id: str, day: date, actor: str, status: str | None = None, owner: str | None = None) -> dict | None:
    if status is not None and status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    row = _rows(conn.execute(
        f"UPDATE ops.issues SET status = COALESCE(%(status)s, status), owner = COALESCE(%(owner)s, owner), "
        f"closed = CASE WHEN %(status)s = '{CLOSED}' THEN %(day)s::date WHEN %(status)s IS NOT NULL THEN NULL ELSE closed END "
        f"WHERE id = %(id)s RETURNING {COLUMNS}", {"status": status, "owner": owner, "day": day, "id": issue_id}))
    if not row:
        return None
    audit(conn, day, actor, "issue.updated", "issue", issue_id, {"status": status, "owner": owner})
    return row[0]
