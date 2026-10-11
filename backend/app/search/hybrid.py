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
    """BM25 + vector + RRF over ai.ae_terms (default) or, with `ChunkSearch`, over ai.protocol_chunks."""
    table, text_col, bm25_index = "ai.ae_terms", "term", "ai.ae_terms_bm25"
    cols = "id, term, coded_term, source"

    def __init__(self, conn: Connection):
        self.conn = conn

    def _query_vector(self, q: str, allow_live: bool) -> list[float] | None:
        if self.table == "ai.ae_terms":
            row = self.conn.execute("SELECT embedding::text FROM ai.ae_terms WHERE upper(term) = upper(%s) AND embedding IS NOT NULL LIMIT 1", (q,)).fetchone()
            if row:
                return [float(x) for x in row[0].strip("[]").split(",")]
        return embed_texts([q], allow_live=allow_live)[0]

    def _bm25(self, q: str, k: int) -> tuple[list[Hit], str]:
        try:
            with self.conn.transaction():   # savepoint: a missing extension must not poison the caller's transaction
                rows = self.conn.execute(
                    f"SELECT {self.cols}, {self.text_col} <@> to_bm25query(%s, '{self.bm25_index}') AS s FROM {self.table} ORDER BY s LIMIT %s", (q, k)).fetchall()
            return [Hit(r[0], r[1], r[2], r[3], i + 1, float(-r[4])) for i, r in enumerate(rows) if r[4] < 0], "bm25"
        except Exception:
            rows = self.conn.execute(
                f"SELECT {self.cols}, ts_rank_cd(to_tsvector('english', {self.text_col}), plainto_tsquery('english', %s)) AS s "
                f"FROM {self.table} WHERE to_tsvector('english', {self.text_col}) @@ plainto_tsquery('english', %s) ORDER BY s DESC LIMIT %s",
                (q, q, k)).fetchall()
            return [Hit(r[0], r[1], r[2], r[3], i + 1, float(r[4])) for i, r in enumerate(rows)], "tsvector (BM25 unavailable)"

    def _vector(self, vec: list[float], k: int) -> list[Hit]:
        rows = self.conn.execute(
            f"SELECT {self.cols}, 1 - (embedding <=> %s::vector) AS sim FROM {self.table} WHERE embedding IS NOT NULL "
            f"ORDER BY embedding <=> %s::vector LIMIT %s", (to_pgvector(vec), to_pgvector(vec), k)).fetchall()
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


class ChunkSearch(HybridSearch):
    """The same hybrid search over the protocol chunks. Hit.term holds the section, Hit.coded_term the chunk text."""
    table, text_col, bm25_index = "ai.protocol_chunks", "text", "ai.protocol_bm25"
    cols = "id, section, text, 'protocol'"
