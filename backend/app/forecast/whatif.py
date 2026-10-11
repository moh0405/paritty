"""What-if forecasts (spec §9.8). The forecast is read-only, so no database fork is needed: the baseline and the hypothetical run on the
same random draws (same seed), and the difference is the effect of the hypothetical alone."""
from __future__ import annotations

from datetime import date

from psycopg import Connection

from app.forecast.service import ForecastService, Hypothetical

CATEGORIES = {"sae_recon", "lab_recon", "expected", "safety", "efficacy", "eligibility", "other"}
MIN_DAYS, MAX_DAYS = 0.5, 60.0


class WhatIfError(ValueError):
    pass


def validate(conn: Connection, h: Hypothetical) -> None:
    sites = {s for (s,) in conn.execute("SELECT site_id FROM edc.sites")}
    for site, days in h.site_response_days.items():
        if site not in sites:
            raise WhatIfError(f"unknown site {site}")
        if not MIN_DAYS <= float(days) <= MAX_DAYS:
            raise WhatIfError(f"response time for site {site} must be between {MIN_DAYS} and {MAX_DAYS:g} days")
    bad = [c for c in h.close_categories if c not in CATEGORIES]
    if bad:
        raise WhatIfError(f"unknown work category: {', '.join(bad)}")
    if not h.site_response_days and not h.close_categories:
        raise WhatIfError("choose at least one change to test")


def describe(h: Hypothetical) -> str:
    parts = [f"site {s} answers queries in about {d:g} days" for s, d in h.site_response_days.items()]
    names = {"sae_recon": "serious adverse event reconciliation", "lab_recon": "lab reconciliation", "expected": "future queries"}
    parts += [f"{names.get(c, c + ' queries')} are already done" for c in h.close_categories]
    return "If " + " and ".join(parts)


class WhatIfRunner:
    def __init__(self, conn: Connection, n_sims: int = 2000):
        self.conn, self.svc = conn, ForecastService(conn, n_sims)

    def run(self, today: date, h: Hypothetical) -> dict:
        validate(self.conn, h)
        h.description = describe(h)
        base, alt = self.svc.run(today), self.svc.run(today, h)
        pick = lambda r: {k: str(r[k]) for k in ("p10", "p50", "p90")}  # noqa: E731
        return {"description": h.description, "baseline": pick(base), "what_if": pick(alt),
                "delta_p50_days": (alt["p50"] - base["p50"]).days, "delta_p90_days": (alt["p90"] - base["p90"]).days,
                "blockers_after": alt["blockers"], "n_sims": self.svc.n_sims}
