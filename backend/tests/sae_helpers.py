from datetime import date, timedelta

from app.recon.sae.matcher import AeRec, CaseRec, Match, TermScore

D = date(2026, 3, 1)
EXACT = TermScore(1.0, "exact")
SAME = TermScore(0.95, "dictionary", "both map to X")
DIFF = TermScore(0.1, "decision", "different events")


def ae(**kw) -> AeRec:
    base = dict(id=1, usubjid="01-701-1001", site_id="701", term_coded="SYNCOPE", onset=D, serious=True, causality="PROBABLE",
                outcome="RECOVERED/RESOLVED", entered_at=D)
    return AeRec(**{**base, **kw})


def case(**kw) -> CaseRec:
    base = dict(row_id=10, case_id="LS1", version=1, usubjid="01-701-1001", term="SYNCOPE", onset=D, serious="1", causality="Related",
                outcome="1", death=None, received=D, available_on=D, narrative="n")
    return CaseRec(**{**base, **kw})


def match(a=None, c=None, term=EXACT) -> Match:
    return Match(a or ae(), c or case(), 1.0, term)


def later(days: int) -> date:
    return D + timedelta(days=days)
