"""Site-behaviour injectors (spec §7.2 personalities applied to a fork's future data)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.evals.injectors.base import InjectContext, Injector, register
from app.seed.common import fetch_df
from app.sim.constants import VISIT_WINDOW_DAYS

TABLES_WITH_ENTRY = ("ae", "lab", "vitals", "visits", "exposure")


@register
class SitePersonality(Injector):
    kind, module = "site_personality", "sites"

    def pick_site(self, ctx: InjectContext, params: dict) -> str:
        if params.get("site"):
            return str(params["site"])
        normal = {s for (s,) in ctx.key.execute("SELECT site_id FROM answer_key.site_personality WHERE personality = 'normal'")}
        active = [s for (s,) in ctx.data.execute("SELECT DISTINCT site_id FROM edc_pending.vitals WHERE entered_at > %s AND entered_at <= %s", (ctx.today, ctx.horizon)) if s in normal]
        return str(ctx.rng.choice(sorted(active)))

    def apply(self, ctx, count, params):
        for _ in range(max(1, count)):
            site, p = self.pick_site(ctx, params), params["personality"]
            getattr(self, f"_{p}")(ctx, site)
            ctx.key.execute("UPDATE answer_key.site_personality SET personality = %s WHERE site_id = %s", (p, site))
            ctx.record(self.kind, self.module, None, None, "personality", "normal", p, None, site)
        return 0

    def _too_perfect(self, ctx, site):
        v = fetch_df(ctx.data, "SELECT id, usubjid, test_code, value FROM edc_pending.vitals WHERE site_id = %s AND entered_at > %s AND entered_at <= %s", (site, ctx.today, ctx.horizon))
        bp = v[v.test_code.isin(["SYSBP", "DIABP"]) & (ctx.rng.random(len(v)) < 0.7)]
        for _, r in bp.iterrows():
            base = 10 if ctx.rng.random() < 0.5 else 5
            ctx.data.execute("UPDATE edc_pending.vitals SET value = %s WHERE id = %s", (float(round(r.value / base) * base), int(r.id)))
        pul = v[v.test_code == "PULSE"]
        for u, g in pul.groupby("usubjid"):
            m = g.value.mean()
            for _, r in g.iterrows():
                ctx.data.execute("UPDATE edc_pending.vitals SET value = %s WHERE id = %s", (float(round(m + 0.3 * (r.value - m))), int(r.id)))

    def _under_reporter(self, ctx, site):
        ctx.data.execute("DELETE FROM edc_pending.ae WHERE site_id = %s AND NOT serious AND entered_at > %s AND entered_at <= %s AND random() < 0.6", (site, ctx.today, ctx.horizon))

    def _sloppy_entry(self, ctx, site):
        for t in TABLES_WITH_ENTRY:
            ctx.data.execute(f"UPDATE edc_pending.{t} SET entered_at = entered_at + (10 + floor(random() * 16))::int WHERE site_id = %s AND entered_at > %s AND entered_at <= %s",
                             (site, ctx.today, ctx.horizon))

    def _rule_bender(self, ctx, site):
        vis = fetch_df(ctx.data, "SELECT id, usubjid, visit, actual_date FROM edc_pending.visits WHERE site_id = %s AND planned_day > 1 AND entered_at > %s AND entered_at <= %s",
                       (site, ctx.today, ctx.horizon))
        for _, r in vis[ctx.rng.random(len(vis)) < 0.25].iterrows():
            d = int(ctx.rng.choice([-1, 1])) * int(ctx.rng.integers(VISIT_WINDOW_DAYS + 2, VISIT_WINDOW_DAYS + 10))
            ctx.data.execute("UPDATE edc_pending.visits SET actual_date = actual_date + %s WHERE id = %s", (d, int(r.id)))
            ctx.data.execute("UPDATE edc_pending.lab SET collected_at = collected_at + make_interval(days => %s) WHERE usubjid = %s AND visit = %s", (d, r.usubjid, r.visit))
            ctx.data.execute("UPDATE edc_pending.vitals SET measured_at = measured_at + make_interval(days => %s) WHERE usubjid = %s AND visit = %s", (d, r.usubjid, r.visit))

    def _slow_responder(self, ctx, site):
        pass       # behaviour lives in the simulator, which reads answer_key.site_personality
