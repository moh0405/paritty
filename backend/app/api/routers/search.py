from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.db.connection import scoped_connection
from app.deps import Caller, get_caller
from app.search.hybrid import HybridSearch

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/terms")
def search_terms(q: Annotated[str, Query(min_length=1)], caller: Annotated[Caller, Depends(get_caller)], k: int = 10) -> dict:
    """BM25 hits, vector hits, the RRF-fused list, and which method ran (spec §13)."""
    with scoped_connection(caller.role, caller.site_scope) as conn:
        r = HybridSearch(conn).search(q, k=min(k, 25), allow_live=True)
    dump = lambda hits: [h.__dict__ for h in hits]  # noqa: E731
    return {"query": r.query, "method": r.method, "bm25": dump(r.bm25), "vector": dump(r.vector), "fused": dump(r.fused)}
