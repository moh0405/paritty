"""Natural-language questions to guarded, read-only SQL with lineage (spec §9.9).
Gemini proposes SQL; our code decides whether it may run: one SELECT, only allow-listed schema-qualified views, no dangerous functions;
it then runs under the caller's role, read-only, with a 5 s timeout and a 500-row limit."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import psycopg
from psycopg import Connection

from app.hub import questions
from app.llm import prompts
from app.llm.client import LLMClient, get_client
from app.llm.schemas import SqlProposal

ALLOWED = ["hub.v_sites", "hub.v_subjects", "hub.v_site_summary", "hub.v_open_items", "hub.v_site_counts", "hub.v_site_monitoring", "hub.v_lab_vendor",
           "hub.v_safety_cases", "hub.v_irt_kits", "hub.v_ctms_sites", "hub.catalog", "hub.dq_results", "ops.lock_forecasts"]
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|call|do|execute|vacuum|analyze|set|reset|listen|notify|lock|into|"
                       r"pg_\w*|lo_\w*|dblink\w*|set_config|current_setting|information_schema|unblinded|answer_key|audit|randomization|arm)\b", re.I)
TIMEOUT_MS, ROW_LIMIT = 5000, 500


class GuardError(ValueError):
    pass


class Unanswerable(Exception):
    pass


def strip_literals(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


_FROM_CLAUSE = re.compile(r"\bfrom\b(.*?)(?=\bwhere\b|\bgroup\b|\border\b|\bhaving\b|\blimit\b|\bunion\b|\bintersect\b|\bexcept\b|\boffset\b|\bwindow\b|$)", re.I | re.S)


def has_comma_join(sql: str) -> bool:
    """True if any FROM clause, at any nesting level, lists tables with commas (which would read a table without FROM/JOIN in front of it)."""
    text = sql
    while True:
        inner = re.search(r"\(([^()]*)\)", text)
        level = inner.group(1) if inner else text
        if any("," in m.group(1) for m in _FROM_CLAUSE.finditer(level)):
            return True
        if not inner:
            return False
        text = text[:inner.start()] + " __sub__ " + text[inner.end():]


def check_sql(sql: str) -> tuple[str, list[str]]:
    """Return (clean sql, relations used) or raise GuardError."""
    s = sql.strip().rstrip(";").strip()
    bare = strip_literals(s)
    if not s:
        raise GuardError("empty query")
    if ";" in bare:
        raise GuardError("only one statement is allowed")
    if "--" in bare or "/*" in bare:
        raise GuardError("comments are not allowed")
    if not re.match(r"^(select|with)\b", bare, re.I):
        raise GuardError("only SELECT queries are allowed")
    bad = FORBIDDEN.search(bare)
    if bad:
        raise GuardError(f"'{bad.group(0)}' is not allowed")
    if has_comma_join(bare):
        raise GuardError("list tables with JOIN, not commas")
    ctes = set(re.findall(r"\b(\w+)\s+as\s*\(", bare, re.I))
    rels = re.findall(r"\b(?:from|join)\s+([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)?)", bare, re.I)
    used = []
    for r in rels:
        r = r.lower()
        if r in {c.lower() for c in ctes}:
            continue
        if "." not in r:
            raise GuardError(f"table '{r}' must be written with its schema, for example hub.v_open_items")
        if r not in ALLOWED:
            raise GuardError(f"'{r}' is not one of the tables this tool can read")
        used.append(r)
    if not used:
        raise GuardError("the query reads no allowed table")
    return s, sorted(set(used))


def schema_text(conn: Connection) -> str:
    out = []
    for rel in ALLOWED:
        schema, name = rel.split(".")
        cols = [f"{c} ({t})" for c, t in conn.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (schema, name))]
        if cols:
            out.append(f"{rel}: " + ", ".join(cols))
    return "\n".join(out)


@dataclass
class AskResult:
    question: str
    sql: str
    explanation: str
    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    source: str = "gemini"
    level: str = "custom"
    note: str = ""


class AskService:
    def __init__(self, conn: Connection, client: LLMClient | None = None, schema_conn: Connection | None = None):
        self.conn = conn                       # acting as the caller's role
        self.client = client if client is not None else get_client()
        self.schema_conn = schema_conn or conn

    def run_guarded(self, sql: str) -> tuple[list[str], list[dict], list[str], str]:
        clean, tables = check_sql(sql)
        try:
            with self.conn.transaction():
                self.conn.execute("SET TRANSACTION READ ONLY")
                self.conn.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
                cur = self.conn.execute(f"SELECT * FROM ({clean}) AS q LIMIT {ROW_LIMIT}")
                cols = [d.name for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        except psycopg.errors.InsufficientPrivilege:
            raise PermissionError("Your role can't see the data behind this question.")
        except psycopg.errors.QueryCanceled:
            raise GuardError("the query took longer than 5 seconds and was stopped")
        except psycopg.Error as exc:
            raise GuardError(f"the query could not run: {str(exc).splitlines()[0]}")
        return cols, rows, tables, clean

    def ask(self, question: str) -> AskResult:
        proposal = None
        try:
            version, prompt = prompts.render("ask_sql", schema=schema_text(self.schema_conn), question=question)
            res = self.client.structured("ask_sql", prompt, SqlProposal, prompt_version=version, conn=self.conn)
            proposal = res.parsed
        except PermissionError:
            raise
        except Exception as exc:
            print(f"warning: NL ask fell back to the standard questions ({type(exc).__name__})")
        if proposal is not None:
            if proposal.refuse:
                raise Unanswerable(proposal.explanation or "That cannot be answered from the data this tool may read.")
            cols, rows, tables, clean = self.run_guarded(proposal.sql)
            return AskResult(question, clean, proposal.explanation, cols, rows, tables, "gemini")
        return self._standard(question)

    def _standard(self, question: str) -> AskResult:
        """Without the AI service: pick the standard cross-system question that best matches the words, if one clearly does."""
        from app.protocol.qa_engine import tokens
        q = tokens(question)
        scored = sorted(((len(q & tokens(x["title"])) / max(1, len(tokens(x["title"]))), x) for x in questions.QUESTIONS), key=lambda t: -t[0])
        score, best = scored[0]
        if score < 0.4:
            raise Unanswerable("The AI service is not available, and this does not match one of the standard questions. Try one of those, or ask again later.")
        out = questions.run(self.conn, best["id"])
        return AskResult(question, out["lineage"]["sql"], f"Closest standard question: {best['title']}", out["columns"], out["rows"], out["lineage"]["tables"],
                         "standard question", out["level"], out["note"])
