"""AE term dictionary lookups over ai.ae_terms: canonical (coded) term and stored embeddings."""
from __future__ import annotations

import math

from psycopg import Connection


def norm_term(t: str | None) -> str:
    return " ".join((t or "").upper().split())


class TermIndex:
    def __init__(self, conn: Connection):
        self.conn = conn
        self._canon: dict[str, str] = {}
        self._vec: dict[str, list[float] | None] = {}

    def canonical(self, term: str) -> str | None:
        """Coded term for an exact dictionary entry (coded, verbatim or synonym), else None."""
        key = norm_term(term)
        if key not in self._canon:
            row = self.conn.execute("SELECT coded_term FROM ai.ae_terms WHERE upper(term) = %s ORDER BY (source = 'coded') DESC, id LIMIT 1", (key,)).fetchone()
            self._canon[key] = row[0] if row else None
        return self._canon[key]

    def vector(self, term: str) -> list[float] | None:
        key = norm_term(term)
        if key not in self._vec:
            row = self.conn.execute("SELECT embedding::text FROM ai.ae_terms WHERE upper(term) = %s AND embedding IS NOT NULL LIMIT 1", (key,)).fetchone()
            self._vec[key] = [float(x) for x in row[0].strip("[]").split(",")] if row else None
        return self._vec[key]


def cosine(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0
