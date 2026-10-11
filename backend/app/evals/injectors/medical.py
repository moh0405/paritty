"""Medical-signal injectors."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from app.evals.injectors.base import InjectContext, Injector, register
from app.medical.ctcae import grade_lab
from app.seed.common import fetch_df

BILI_UMOL = 17.1


def set_lab(ctx: InjectContext, usubjid: str, visit: str, test: str, x_uln: float) -> int | None:
    """Set a pending lab result to a multiple of its ULN, keeping the central-lab copy consistent."""
    row = ctx.data.execute("SELECT id, uln, lln, unit FROM edc_pending.lab WHERE usubjid = %s AND visit = %s AND test_code = %s AND uln > 0 "
                           "AND entered_at > %s AND entered_at <= %s ORDER BY collected_at LIMIT 1", (usubjid, visit, test, ctx.today, ctx.horizon)).fetchone()
    if row is None:
        return None
    lid, uln, lln, unit = row
    value = round(x_uln * uln, 2)
    ctx.data.execute("UPDATE edc_pending.lab SET value = %s, x_uln = %s, ctcae_grade = %s WHERE id = %s", (value, x_uln, grade_lab(test, value, uln, lln, unit), lid))
    ctx.data.execute("UPDATE lab_vendor.transfer SET result = %s WHERE accession_no = %s", (str(round(value * BILI_UMOL, 2) if test == "BILI" else value), f"ACC-{lid:07d}"))
    ctx.used.setdefault("lab", set()).add(lid)
    return lid


@register
class HysLawPlant(Injector):
    kind, module = "hys_law_plant", "medical"

    def apply(self, ctx, count, params):
        lab = ctx.window("lab", "usubjid, site_id, visit, test_code", "uln > 0 AND test_code IN ('ALT','AST','BILI','ALP')")
        g = lab.groupby(["usubjid", "site_id", "visit"]).test_code.nunique()
        cands = [(u, s, v) for (u, s, v), n in g.items() if n == 4]
        ctx.rng.shuffle(cands)
        used_sites: set[str] = set()
        planted = 0
        for u, site, visit in cands:
            if planted >= count:
                break
            if site in used_sites:
                continue
            ids = [set_lab(ctx, u, visit, t, x) for t, x in (("ALT", 5.0), ("AST", 4.2), ("BILI", 3.1), ("ALP", 1.2))]
            if ids[0] is None:
                continue
            used_sites.add(site)
            ctx.record(self.kind, self.module, "edc.lab", ids[0], "ALT/AST/BILI x ULN", "normal", "5.0/4.2/3.1", u, site)
            planted += 1
        return 0


@register
class SiteCreep(Injector):
    kind, module = "site_creep", "medical"

    def apply(self, ctx, count, params):
        growth = float(params.get("growth_per_visit", 0.25))
        sites = [s for (s,) in ctx.data.execute("SELECT DISTINCT site_id FROM edc_pending.lab WHERE test_code = 'ALT' AND entered_at > %s AND entered_at <= %s", (ctx.today, ctx.horizon))]
        site = params.get("site") or str(ctx.rng.choice(sorted(sites)))
        rows = fetch_df(ctx.data, "SELECT id, usubjid, value, uln, lln, unit, collected_at FROM edc_pending.lab WHERE site_id = %s AND test_code = 'ALT' AND uln > 0 "
                                  "AND entered_at > %s AND entered_at <= %s ORDER BY usubjid, collected_at", (site, ctx.today, ctx.horizon))
        rows["k"] = rows.groupby("usubjid").cumcount()
        for _, r in rows.iterrows():
            val = round(float(r.value) * (1 + growth) ** int(r.k), 2)
            ctx.data.execute("UPDATE edc_pending.lab SET value = %s, x_uln = %s, ctcae_grade = %s WHERE id = %s", (val, val / r.uln, grade_lab("ALT", val, r.uln, r.lln, r.unit), int(r.id)))
            ctx.data.execute("UPDATE lab_vendor.transfer SET result = %s WHERE accession_no = %s", (str(val), f"ACC-{int(r.id):07d}"))
            ctx.used.setdefault("lab", set()).add(int(r.id))
        ctx.record(self.kind, self.module, "edc.lab", None, "ALT x ULN slope", "flat", f"+{growth:.0%} per visit", None, site)
        return 0


@register
class RareAeCluster(Injector):
    kind, module = "rare_ae_cluster", "medical"

    def apply(self, ctx, count, params):
        term = params.get("term", "DYSGEUSIA")
        sites = fetch_df(ctx.data, "SELECT site_id, count(*) n FROM edc.subjects GROUP BY 1 HAVING count(*) >= 4")
        site = params.get("site") or str(ctx.rng.choice(sites.site_id.tolist()))
        subs = fetch_df(ctx.data, "SELECT usubjid FROM edc.subjects WHERE site_id = %s AND status = 'enrolled' LIMIT 40", (site,))
        for u in ctx.rng.choice(subs.usubjid.tolist(), min(max(count, 3), len(subs)), replace=False):
            onset = ctx.today + timedelta(days=int(ctx.rng.integers(2, max(3, (ctx.horizon - ctx.today).days - 3))))
            new_id = ctx.data.execute("INSERT INTO edc_pending.ae (usubjid, site_id, source_seq, term_verbatim, term_coded, onset_at, serious, severity, ctcae_grade, causality, outcome, entered_at) "
                                      "VALUES (%s,%s,950,%s,%s,%s,false,'MILD',1,'POSSIBLE','NOT RECOVERED/NOT RESOLVED',%s) RETURNING id",
                                      (u, site, term, term, onset, onset + timedelta(days=2))).fetchone()[0]
            ctx.record(self.kind, self.module, "edc.ae", new_id, "term_coded", None, term, u, site)
        return 0


@register
class AeLabLinkInjector(Injector):
    kind, module = "ae_lab_link", "medical"

    def apply(self, ctx, count, params):
        df = ctx.window("lab", "id, usubjid, site_id, test_code, uln, lln, unit, collected_at", "test_code IN ('PLAT','HGB') AND uln > 0")
        for _, r in ctx.pick(df, count, "lab").iterrows():
            plat = r.test_code == "PLAT"
            val = 60.0 if plat else 5.9
            ctx.data.execute("UPDATE edc_pending.lab SET value = %s, x_uln = %s, ctcae_grade = %s WHERE id = %s", (val, val / r.uln, grade_lab(r.test_code, val, r.uln, r.lln, r.unit), int(r.id)))
            ctx.data.execute("UPDATE lab_vendor.transfer SET result = %s WHERE accession_no = %s", (str(val), f"ACC-{int(r.id):07d}"))
            onset = pd.Timestamp(r.collected_at).date() + timedelta(days=int(ctx.rng.integers(-4, 5)))
            term = "THROMBOCYTOPENIA" if plat else "ANAEMIA"
            ae = ctx.data.execute("INSERT INTO edc_pending.ae (usubjid, site_id, source_seq, term_verbatim, term_coded, onset_at, serious, severity, ctcae_grade, causality, outcome, entered_at) "
                                  "VALUES (%s,%s,951,%s,%s,%s,false,'MODERATE',2,'POSSIBLE','NOT RECOVERED/NOT RESOLVED',%s) RETURNING id",
                                  (r.usubjid, r.site_id, term, term, onset, max(onset, pd.Timestamp(r.collected_at).date()) + timedelta(days=3))).fetchone()[0]
            ctx.record(self.kind, self.module, "edc.lab", int(r.id), f"{r.test_code} grade 2 + AE", None, ae, r.usubjid, r.site_id)
        return 0
