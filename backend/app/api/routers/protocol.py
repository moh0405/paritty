import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.audit.logger import audit
from app.db.connection import get_pool, scoped_connection
from app.deps import Caller, get_caller
from app.protocol.qa_engine import ProtocolQA
from app.search.hybrid import ChunkSearch
from app.sim.clock import TrialClock

router = APIRouter(tags=["protocol"])


class AskIn(BaseModel):
    question: str
    site_id: str | None = None


@router.post("/protocol/ask")
def ask(body: AskIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    """Eligibility assistant and site concierge: a quoted answer, or an escalation. The answer is saved as a draft that a person approves
    before it goes anywhere (spec §2 rule 2)."""
    with scoped_connection(caller.role, caller.site_scope) as probe:
        probe.execute("SELECT 1 FROM ai.protocol_chunks LIMIT 1")        # role check: study lead has no access to protocol text here
    with get_pool().connection() as conn:
        r = ProtocolQA(conn).ask(body.question.strip())
        payload = {"question": r.question, "answer": r.answer, "quotes": r.quotes, "escalate": r.escalate, "confidence": r.confidence, "reason": r.reason, "source": r.source}
        did = str(conn.execute("INSERT INTO ops.drafts (kind, subject_ref, site_id, body, state) VALUES ('eligibility', NULL, %s, %s, 'draft') RETURNING id",
                               (body.site_id, json.dumps({**payload, "text": r.answer}))).fetchone()[0])
        audit(conn, TrialClock(conn).today(), caller.user, "protocol.asked", "draft", did, {"escalate": r.escalate, "source": r.source}, role=caller.role.value)
    return {**payload, "draft_id": did}


@router.get("/search/protocol")
def search_protocol(q: Annotated[str, Query(min_length=1)], caller: Annotated[Caller, Depends(get_caller)], k: int = 6) -> dict:
    with scoped_connection(caller.role, caller.site_scope) as conn:
        res = ChunkSearch(conn).search(q, k=min(k, 12), allow_live=True)
    hit = lambda h: {"chunk_id": h.id, "section": h.term, "text": h.coded_term, "rank": h.rank, "score": h.score}  # noqa: E731
    return {"query": q, "method": res.method, "bm25": [hit(h) for h in res.bm25], "vector": [hit(h) for h in res.vector], "fused": [hit(h) for h in res.fused]}
