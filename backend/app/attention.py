"""What is waiting for a person today, by role (the 'Today' page and the sidebar badges).

Every generated check, query, note, letter and agent action waits for a human (spec §2 rule 2); those decisions live on
many pages. This module only counts them: no patient-level rows and no treatment arm leave it, so any role may see the counts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from psycopg import Connection

from app.domain.enums import Role
from app.sites import visit_planner

DM, MM, CM, SL = Role.DATA_MANAGER, Role.MEDICAL_MONITOR, Role.CENTRAL_MONITOR, Role.STUDY_LEAD
DECIDE, WATCH = "decide", "watch"          # decide: nothing moves until a person acts; watch: open work to keep an eye on
SCOPE = "(%(scope)s::text IS NULL OR site_id = ANY(string_to_array(%(scope)s, ',')))"
OPEN_QUERY = "q.state IN ('Draft','Approved','Sent','Answered','Reopened')"


@dataclass(frozen=True)
class Source:
    key: str
    one: str                    # wording for a count of one
    many: str                   # wording for any other count
    href: str                   # the page where the person acts
    roles: frozenset[Role]      # who acts on it
    kind: str
    help: str                   # one plain sentence: what it is and what happens when you act
    sql: str | None = None      # returns one count; None when the count is computed in code


SOURCES: list[Source] = [
    Source("query_drafts", "query draft to approve", "query drafts to approve", "/queries", frozenset({DM}), DECIDE,
           "A check found a problem and a question to the site is drafted. It is sent only after you approve it.",
           f"SELECT count(*) FROM ops.queries WHERE state = 'Draft' AND {SCOPE}"),
    Source("query_answers", "site answer to decide on", "site answers to decide on", "/queries", frozenset({DM}), DECIDE,
           "The site replied without changing the data. Accept the explanation to close the query, or reopen it.",
           f"SELECT count(*) FROM ops.queries WHERE state = 'Answered' AND {SCOPE}"),
    Source("digests", "weekly digest to approve", "weekly digests to approve", "/queries", frozenset({DM}), DECIDE,
           "Minor issues are bundled into one message per site each week. Approving the digest approves its queries.",
           f"SELECT count(*) FROM ops.digests WHERE state = 'Draft' AND {SCOPE}"),
    Source("generated_checks", "proposed check to approve or reject", "proposed checks to approve or reject", "/checks", frozenset({DM}), DECIDE,
           "A new data check was proposed from the protocol text. It does not run until you approve it.",
           "SELECT count(*) FROM ops.check_specs WHERE approval_status = 'pending_approval'"),
    Source("notes", "review note to sign", "review notes to sign", "/medical", frozenset({MM}), DECIDE,
           "A medical review note was drafted for a flagged patient. It counts only once a medical monitor signs it.",
           f"SELECT count(*) FROM ops.drafts WHERE kind = 'note' AND state = 'draft' AND {SCOPE}"),
    Source("medical_review", "flagged finding to review", "flagged findings to review", "/medical", frozenset({MM}), DECIDE,
           "A lab pattern or cluster was flagged as a reason to look. Mark it reviewed or escalate it.",
           f"SELECT count(*) FROM ai.findings WHERE module = 'medical' AND review_status = 'open' AND verification_status <> 'blocked' AND {SCOPE}"),
    Source("escalations", "open escalation", "open escalations", "/medical", frozenset({MM}), DECIDE,
           "A finding was escalated and is waiting to be acknowledged or resolved.",
           "SELECT count(*) FROM ops.escalations WHERE status = 'open'"),
    Source("eligibility", "eligibility answer to approve", "eligibility answers to approve", "/ask", frozenset({MM, DM}), DECIDE,
           "An answer to a site's protocol question was drafted with quotes. It is sent only after approval.",
           f"SELECT count(*) FROM ops.drafts WHERE kind = 'eligibility' AND state = 'draft' AND {SCOPE}"),
    Source("site_documents", "agenda or letter to approve", "agendas and letters to approve", "/sites/visit-plan", frozenset({CM, DM}), DECIDE,
           "A visit agenda or follow-up letter was drafted for a site. Approving it opens tracked issues.",
           f"SELECT count(*) FROM ops.drafts WHERE kind IN ('agenda','letter') AND state = 'draft' AND {SCOPE}"),
    Source("issues", "open site issue", "open site issues", "/sites", frozenset({CM, DM}), DECIDE,
           "An approved agenda point or letter is being tracked until someone closes it.",
           f"SELECT count(*) FROM ops.issues WHERE status <> 'closed' AND {SCOPE}"),
    Source("agent_actions", "suggested action to approve", "suggested actions to approve", "/agent", frozenset({DM, SL}), DECIDE,
           "The agent proposed an action with its expected effect on the lock date. Nothing happens until you approve it.",
           f"SELECT count(*) FROM ops.drafts WHERE kind = 'agent_action' AND state = 'draft' AND {SCOPE}"),
    Source("unmatched_ids", "identifier to match by hand", "identifiers to match by hand", "/hub", frozenset({DM, CM}), DECIDE,
           "An identifier from another system could not be matched to a subject or site with confidence.",
           "SELECT (SELECT count(*) FROM hub.subject_xwalk WHERE status = 'unmatched') + (SELECT count(*) FROM hub.site_xwalk WHERE status = 'unmatched')"),
    Source("critical_queries", "open critical query", "open critical queries", "/queries", frozenset({DM}), WATCH,      # the study lead sees these on the lock readiness page
           "Critical queries block database lock while they are open.",
           f"SELECT count(*) FROM ops.queries q JOIN ops.check_failures f ON f.id = q.failure_id JOIN ops.check_specs s ON s.id = f.check_id "
           f"WHERE {OPEN_QUERY} AND s.severity = 'critical' AND {SCOPE.replace('site_id', 'q.site_id')}"),
    Source("sae_open", "open safety report difference", "open safety report differences", "/recon/sae", frozenset({DM, MM}), WATCH,
           "A serious adverse event differs between the trial database and the safety database.",
           f"SELECT count(*) FROM ops.check_failures WHERE resolved_on IS NULL AND (check_id LIKE 'sae\\_%%' OR check_id = 'chk_22') AND {SCOPE}"),
    Source("lab_open", "open central lab difference", "open central lab differences", "/recon/labs", frozenset({DM}), WATCH,
           "A central lab result differs from what the site entered.",
           f"SELECT count(*) FROM ops.check_failures WHERE resolved_on IS NULL AND check_id IN ('chk_24','chk_25','chk_26') AND {SCOPE}"),
    Source("sites_to_contact", "site proposed for a visit or call", "sites proposed for a visit or call", "/sites/visit-plan", frozenset({CM}), WATCH,
           "Sites whose indicators suggest a visit, a call or a remote review this month."),
]
BY_KEY = {s.key: s for s in SOURCES}


def count_all(conn: Connection, today: date, scope: str | None = None) -> dict[str, int]:
    counts = {s.key: int(conn.execute(s.sql, {"scope": scope}).fetchone()[0]) for s in SOURCES if s.sql}
    allowed = set(scope.split(",")) if scope else None
    counts["sites_to_contact"] = sum(1 for r in visit_planner.plan(conn, today)["sites"] if allowed is None or r["site_id"] in allowed)
    return counts


def build(counts: dict[str, int], role: Role) -> list[dict]:
    """Everything with something waiting, the caller's own work first, decisions before things to watch, biggest first."""
    items = [{"key": s.key, "count": n, "title": f"{n} {s.one if n == 1 else s.many}", "href": s.href, "kind": s.kind, "help": s.help,
              "mine": role in s.roles, "roles": sorted(r.value for r in s.roles)}
             for s in SOURCES if (n := counts.get(s.key, 0)) > 0]
    return sorted(items, key=lambda i: (not i["mine"], i["kind"] != DECIDE, -i["count"], i["key"]))


def badges(items: list[dict]) -> dict[str, int]:
    """Decisions waiting for the caller, per page (the sidebar shows these)."""
    out: dict[str, int] = {}
    for i in items:
        if i["mine"] and i["kind"] == DECIDE:
            out[i["href"]] = out.get(i["href"], 0) + i["count"]
    return out


def summary(conn: Connection, role: Role, today: date, scope: str | None = None) -> dict:
    items = build(count_all(conn, today, scope), role)
    lock = conn.execute("SELECT p10, p50, p90, readiness->>'met', readiness->>'total' FROM ops.lock_forecasts ORDER BY sim_date DESC LIMIT 1").fetchone()
    return {"role": role.value, "today": str(today), "items": items, "badges": badges(items),
            "decisions": sum(i["count"] for i in items if i["mine"] and i["kind"] == DECIDE),
            "lock": None if lock is None else {"p10": str(lock[0]), "p50": str(lock[1]), "p90": str(lock[2]), "met": int(lock[3] or 0), "total": int(lock[4] or 0)}}
