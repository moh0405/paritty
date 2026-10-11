"""Eligibility assistant accuracy and escalation precision/recall over the 40 questions (spec §9.10 'done when').
The questions and expected answers live in answer_key.eligibility_qa, so only the eval side reads them. Retrieval uses cached embeddings only."""
import psycopg

from app.protocol.qa_engine import ProtocolQA
from app.verification.normalize import norm_ws


def score(app: psycopg.Connection, key: psycopg.Connection) -> dict:
    qa = ProtocolQA(app, allow_live_embedding=False)
    rows = key.execute("SELECT id, question, expected_quote, should_escalate FROM answer_key.eligibility_qa ORDER BY id").fetchall()
    tp = fp = fn = 0
    answered_ok = answerable = 0
    misses = []
    for _id, question, expected_quote, should in rows:
        r = qa.ask(question)
        if should:
            tp += r.escalate
            fn += not r.escalate
        else:
            fp += r.escalate
            answerable += 1
            hit = (not r.escalate) and any(norm_ws(expected_quote) in norm_ws(q["text"]) or norm_ws(q["text"]) in norm_ws(expected_quote) for q in r.quotes)
            answered_ok += hit
            if not hit:
                misses.append((_id, question, r.escalate, [q["text"][:60] for q in r.quotes]))
    p = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    return {"accuracy": answered_ok / answerable if answerable else 0.0, "escalation_precision": p, "escalation_recall": rc, "n": len(rows), "misses": misses}
