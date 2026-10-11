"""Hybrid search: BM25 (pg_textsearch) + vector (diskann) fused with reciprocal rank fusion (spec §7.6, §9.5, §18).
If BM25 is unavailable it falls back to tsvector ranking; without a query vector it is lexical only. The method used is reported."""
from __future__ import annotations

from dataclasses import dataclass, field

from psycopg import Connection, sql

from app.llm.embed import embed_texts, to_pgvector

RRF_K = 60


@dataclass
class Hit:
    id: int
    term: str
    coded_term: str
    source: str
    rank: int
    score: float


@dataclass
class SearchResult:
    query: str
    bm25: list[Hit] = field(default_factory=list)
    vector: list[Hit] = field(default_factory=list)
    fused: list[Hit] = field(default_factory=list)
    method: str = ""


class HybridSearch:
    """Searches ai.ae_terms. (Protocol chunks use the same pattern in milestone 12.)"""

    def __init__(self, conn: Connection):
        self.conn = conn

    def _query_vector(self, q: str, allow_live: bool) -> list[float] | None:
        row = self.conn.execute("SELECT embedding::text FROM ai.ae_terms WHERE upper(term) = upper(%s) AND embedding IS NOT NULL LIMIT 1", (q,)).fetchone()
        if row:
            return [float(x) for x in row[0].strip("[]").split(",")]
        return embed_texts([q], allow_live=allow_live)[0]

    def _bm25(self, q: str, k: int) -> tuple[list[Hit], str]:
        try:
            with self.conn.transaction():   # savepoint: a missing extension must not poison the caller's transaction
                rows = self.conn.execute(
                    "SELECT id, term, coded_term, source, term <@> to_bm25query(%s, 'ai.ae_terms_bm25') AS s FROM ai.ae_terms "
                    "ORDER BY s LIMIT %s", (q, k)).fetchall()
            return [Hit(r[0], r[1], r[2], r[3], i + 1, float(-r[4])) for i, r in enumerate(rows) if r[4] < 0], "bm25"
        except Exception:
            rows = self.conn.execute(
                "SELECT id, term, coded_term, source, ts_rank_cd(to_tsvector('english', term), plainto_tsquery('english', %s)) AS s "
                "FROM ai.ae_terms WHERE to_tsvector('english', term) @@ plainto_tsquery('english', %s) ORDER BY s DESC LIMIT %s",
                (q, q, k)).fetchall()
            return [Hit(r[0], r[1], r[2], r[3], i + 1, float(r[4])) for i, r in enumerate(rows)], "tsvector (BM25 unavailable)"

    def _vector(self, vec: list[float], k: int) -> list[Hit]:
        rows = self.conn.execute(
            "SELECT id, term, coded_term, source, 1 - (embedding <=> %s::vector) AS sim FROM ai.ae_terms WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> %s::vector LIMIT %s", (to_pgvector(vec), to_pgvector(vec), k)).fetchall()
        return [Hit(r[0], r[1], r[2], r[3], i + 1, float(r[4])) for i, r in enumerate(rows)]

    def search(self, q: str, k: int = 10, allow_live: bool = False) -> SearchResult:
        res = SearchResult(q)
        res.bm25, lexical = self._bm25(q, k)
        vec = self._query_vector(q, allow_live)
        res.vector = self._vector(vec, k) if vec else []
        res.method = f"{lexical} + vector (RRF)" if res.vector else f"{lexical} only (no query vector)"
        scores: dict[int, float] = {}
        by_id: dict[int, Hit] = {}
        for hits in (res.bm25, res.vector):
            for h in hits:
                scores[h.id] = scores.get(h.id, 0.0) + 1.0 / (RRF_K + h.rank)
                by_id[h.id] = h
        res.fused = [Hit(i, by_id[i].term, by_id[i].coded_term, by_id[i].source, rank + 1, s)
                     for rank, (i, s) in enumerate(sorted(scores.items(), key=lambda x: -x[1])[:k])]
        return res
