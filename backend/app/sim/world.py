"""The simulated world's hidden parameters (site personalities).

This is the *simulator*, not a detector: it reads answer_key.site_personality through the privileged
eval_admin connection so that detector/app code (checks, queries, recon...) never needs answer_key access (spec §2 rule 7).
Nothing outside app/sim may import this module.
"""
from __future__ import annotations

import psycopg

from app.config import get_settings
from app.sim.personalities import PARAMS, Personality, PersonalityParams


class WorldModel:
    def __init__(self) -> None:
        with psycopg.connect(get_settings().eval_admin_url) as conn:
            self._p = {s: Personality(p) for s, p in conn.execute("SELECT site_id, personality FROM answer_key.site_personality")}

    def params(self, site_id: str) -> PersonalityParams:
        return PARAMS[self._p.get(site_id, Personality.NORMAL)]
