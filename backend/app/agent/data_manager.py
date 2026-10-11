"""The data-manager agent (spec §9.11, 'extra'): proposes up to five actions with the expected effect on the lock date.
Selection and impact estimates are deterministic (the forecast simulation); Gemini only explains, and its explanation is used only if every
number in it is one the simulation produced. Every action is a draft that a person approves; approving it makes it take effect."""
from __future__ import annotations

import json
from datetime import date

from psycopg import Connection

from app.agent.tools import ACTIONS, MIN_GAIN_DAYS, AgentTools, Candidate
from app.audit.logger import audit
from app.llm import prompts
from app.llm.client import LLMClient, get_client
from app.llm.schemas import AgentPlan
from app.verification.normalize import extract_numbers

MAX_ACTIONS = 5


def template_rationale(c: Candidate) -> str:
    when = "the most likely lock date would move about %d days earlier" % round(c.est_delta_p50_days)
    return (f"Site {c.site_id} has {c.open_queries} open queries and usually answers in about {round(c.current_days)} days. "
            f"If {ACTIONS[c.kind]['phrase']} brought that to about {round(c.target_days)} days, {when}.")


def numbers_ok(text: str, allowed: set[float]) -> bool:
    """Every number in the explanation must be one of the simulation's numbers (rounded)."""
    return all(any(abs(n - a) <= 0.5 for a in allowed) for n in extract_numbers(text))


class DataManagerAgent:
    def __init__(self, conn: Connection, client: LLMClient | None = None, n_sims: int = 600):
        self.conn = conn
        self.client = client if client is not None else get_client()
        self.tools = AgentTools(conn, n_sims)

    def choose(self, day: date) -> list[Candidate]:
        best: dict[str, Candidate] = {}
        for c in self.tools.candidates(day):
            if c.est_delta_p50_days >= MIN_GAIN_DAYS and not self.tools.recently_proposed(c.site_id, c.kind, day):
                if c.site_id not in best or c.est_delta_p50_days > best[c.site_id].est_delta_p50_days:
                    best[c.site_id] = c
        return sorted(best.values(), key=lambda c: -c.est_delta_p50_days)[:MAX_ACTIONS]

    def explain(self, chosen: list[Candidate]) -> dict[str, tuple[str, str]]:
        """candidate id -> (rationale, source). The AI's wording is accepted per action only if its numbers are the simulation's."""
        out = {c.id: (template_rationale(c), "template") for c in chosen}
        if not chosen:
            return out
        try:
            cj = json.dumps([{"candidate_id": c.id, "site": c.site_id, "action": c.label, "open_queries": c.open_queries, "usual_response_days": round(c.current_days),
                              "target_response_days": round(c.target_days), "expected_days_earlier": round(c.est_delta_p50_days)} for c in chosen], indent=1)
            version, prompt = prompts.render("agent_plan", candidates_json=cj)
            res = self.client.structured("agent_plan", prompt, AgentPlan, prompt_version=version, conn=self.conn)
            if res.parsed is not None:
                by = {c.id: c for c in chosen}
                for a in res.parsed.actions:
                    c = by.get(a.candidate_id)
                    if c and a.rationale.strip() and numbers_ok(a.rationale, c.numbers()):
                        out[c.id] = (a.rationale.strip(), "gemini")
        except Exception as exc:
            print(f"warning: agent explanations fell back to the template ({type(exc).__name__})")
        return out

    def plan(self, day: date, actor: str = "agent") -> list[str]:
        chosen = self.choose(day)
        why = self.explain(chosen)
        ids = [self.tools.draft_action(c, *why[c.id], day) for c in chosen]
        for i in ids:
            audit(self.conn, day, actor, "agent.proposed", "draft", i, {}, role=None)
        return ids
