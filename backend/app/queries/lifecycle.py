"""Query lifecycle as a State pattern (spec §9.3):
Draft -> Approved -> Sent -> Answered -> Closed | Reopened | ClosedWithExplanation. Every transition writes ops.query_events + audit.log."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import ClassVar

from psycopg import Connection

from app.audit.logger import audit, sim_ts

DRAFT, APPROVED, SENT, ANSWERED = "Draft", "Approved", "Sent", "Answered"
CLOSED, REOPENED, EXPLAINED = "Closed", "Reopened", "ClosedWithExplanation"
OPEN_STATES = (DRAFT, APPROVED, SENT, ANSWERED, REOPENED)


class IllegalTransition(Exception):
    pass


@dataclass
class Ctx:
    conn: Connection
    query_id: str
    day: date
    actor: str
    detail: dict | None = None


class QueryState:
    name: ClassVar[str]
    transitions: ClassVar[dict[str, str]] = {}      # action -> next state

    def apply(self, action: str, ctx: Ctx) -> str:
        nxt = self.transitions.get(action)
        if nxt is None:
            raise IllegalTransition(f"cannot {action} a query in state {self.name}")
        return nxt


class DraftState(QueryState):
    name = DRAFT
    transitions = {"approve": APPROVED, "close": CLOSED}


class ApprovedState(QueryState):
    name = APPROVED
    transitions = {"send": SENT, "close": CLOSED}


class SentState(QueryState):
    name = SENT
    transitions = {"answer": ANSWERED, "close": CLOSED}


class AnsweredState(QueryState):
    name = ANSWERED
    transitions = {"close": CLOSED, "reopen": REOPENED, "close_with_explanation": EXPLAINED}


class ReopenedState(QueryState):
    name = REOPENED
    transitions = {"send": SENT, "close": CLOSED}


class ClosedState(QueryState):
    name = CLOSED


class ExplainedState(QueryState):
    name = EXPLAINED


STATES: dict[str, QueryState] = {s.name: s for s in
                                 (DraftState(), ApprovedState(), SentState(), AnsweredState(), ReopenedState(), ClosedState(), ExplainedState())}
EVENT = {"approve": "approved", "send": "sent", "answer": "answered", "close": "closed", "reopen": "reopened",
         "close_with_explanation": "closed_with_explanation"}


def transition(ctx: Ctx, action: str, set_cols: dict | None = None) -> str:
    """Apply `action` to the query, persist the new state, and log the event. Raises IllegalTransition."""
    row = ctx.conn.execute("SELECT state, site_id FROM ops.queries WHERE id = %s FOR UPDATE", (ctx.query_id,)).fetchone()
    if row is None:
        raise KeyError(ctx.query_id)
    state, site_id = row
    nxt = STATES[state].apply(action, ctx)
    cols = {"state": nxt, **(set_cols or {})}
    if action == "send":
        cols["sent_on"] = ctx.day
    elif action == "answer":
        cols["answered_on"] = ctx.day
    elif action in ("close", "close_with_explanation"):
        cols["closed_on"] = ctx.day
    elif action == "approve":
        cols["approved_by"] = ctx.actor
    sets = ", ".join(f"{k} = %({k})s" for k in cols)
    if action == "reopen":
        sets += ", reopen_count = reopen_count + 1"
    ctx.conn.execute(f"UPDATE ops.queries SET {sets} WHERE id = %(id)s", {**cols, "id": ctx.query_id})
    ctx.conn.execute(
        "INSERT INTO ops.query_events (ts, sim_date, query_id, site_id, event, actor, detail) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (sim_ts(ctx.day), ctx.day, ctx.query_id, site_id, EVENT[action], ctx.actor, json.dumps(ctx.detail or {})))
    audit(ctx.conn, ctx.day, ctx.actor, f"query.{EVENT[action]}", "query", ctx.query_id, {"from": state, "to": nxt, **(ctx.detail or {})})
    return nxt


def log_drafted(conn: Connection, query_id: str, site_id: str, day: date, actor: str, detail: dict) -> None:
    conn.execute("INSERT INTO ops.query_events (ts, sim_date, query_id, site_id, event, actor, detail) VALUES (%s,%s,%s,%s,'opened',%s,%s)",
                 (sim_ts(day), day, query_id, site_id, actor, json.dumps(detail)))
    audit(conn, day, actor, "query.opened", "query", query_id, detail)
