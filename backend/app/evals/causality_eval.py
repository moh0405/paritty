"""Causality assessments against the deterministic reference labels (spec §9.5): agreement and Cohen's kappa. Eval side only."""
import psycopg
from sklearn.metrics import cohen_kappa_score

from app.recon.sae.causality import CausalityAssessor


def score(app: psycopg.Connection, key: psycopg.Connection, day, sample: int = 15) -> dict:
    """Assess up to `sample` cases not yet assessed, then compare every AI assessment (not worksheets) with the reference."""
    assessor = CausalityAssessor(app)
    cases = [c for (c,) in app.execute("SELECT DISTINCT safetyreportid FROM safety.v_cases WHERE available_on <= %s ORDER BY 1", (day,))]
    done = {c for (c,) in app.execute("SELECT case_id FROM ai.causality_assessments")}
    for cid in [c for c in cases if c not in done][:sample]:
        assessor.assess(cid, day, "eval")
    latest = {c: (cat, esc, src) for c, cat, esc, src in app.execute(
        "SELECT DISTINCT ON (case_id) case_id, category, escalate, body->>'source' FROM ai.causality_assessments ORDER BY case_id, created_at DESC")}
    ref = dict(key.execute("SELECT case_id, category FROM answer_key.causality_reference"))
    ai = {c: v for c, v in latest.items() if v[2] == "gemini" and v[0] != "unassessable" and c in ref}
    out = {"assessed": len(latest), "ai_assessed": len(ai), "escalated_share": (sum(v[1] for v in latest.values()) / len(latest)) if latest else 0.0}
    if ai:
        y, p = [ref[c] for c in ai], [ai[c][0] for c in ai]
        out["agreement"] = sum(a == b for a, b in zip(y, p)) / len(y)
        out["kappa"] = float(cohen_kappa_score(y, p)) if len(set(y) | set(p)) > 1 else 1.0
    return out
