"""Edit-check injectors: errors a data manager's checks should catch."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from app.evals.injectors.base import InjectContext, Injector, register


@register
class ImpossibleValue(Injector):
    kind, module = "impossible_value", "checks"

    def apply(self, ctx: InjectContext, count: int, params: dict) -> int:
        df = ctx.window("vitals", "id, usubjid, site_id, test_code, value", "test_code IN ('SYSBP','DIABP','PULSE')")
        for _, r in ctx.pick(df, count, "vitals").iterrows():
            new = float(ctx.rng.choice({"SYSBP": [260, 310, 400], "DIABP": [170, 220, 260], "PULSE": [8, 220, 300]}[r.test_code]))
            ctx.data.execute("UPDATE edc_pending.vitals SET value = %s WHERE id = %s", (new, r.id))
            ctx.record(self.kind, self.module, "edc.vitals", r.id, "value", r.value, new, r.usubjid, r.site_id)
        return 0


@register
class DateOrder(Injector):
    kind, module = "date_order", "checks"

    def apply(self, ctx: InjectContext, count: int, params: dict) -> int:
        df = ctx.window("ae", "id, usubjid, site_id, onset_at, end_at", "NOT serious AND end_at IS NOT NULL")
        for _, r in ctx.pick(df, count, "ae").iterrows():
            new = pd.Timestamp(r.onset_at).date() - timedelta(days=int(ctx.rng.integers(3, 20)))
            ctx.data.execute("UPDATE edc_pending.ae SET end_at = %s WHERE id = %s", (new, r.id))
            ctx.record(self.kind, self.module, "edc.ae", r.id, "end_at", r.end_at, new, r.usubjid, r.site_id)
        return 0


@register
class UnitMixup(Injector):
    kind, module = "unit_mixup", "checks"

    def apply(self, ctx: InjectContext, count: int, params: dict) -> int:
        df = ctx.window("vitals", "id, usubjid, site_id, value", "test_code = 'TEMP'")
        for _, r in ctx.pick(df, count, "vitals").iterrows():      # degrees F entered as C
            new = round(r.value * 9 / 5 + 32, 1)
            ctx.data.execute("UPDATE edc_pending.vitals SET value = %s WHERE id = %s", (new, r.id))
            ctx.record(self.kind, self.module, "edc.vitals", r.id, "value", r.value, new, r.usubjid, r.site_id)
        return 0


@register
class MissingVisit(Injector):
    kind, module = "missing_visit", "checks"

    def apply(self, ctx: InjectContext, count: int, params: dict) -> int:
        df = ctx.window("visits", "id, usubjid, site_id, visit, planned_day",
                        "visit LIKE 'WEEK%%' AND visit NOT LIKE '%%(T)' AND planned_day >= 28 AND EXISTS (SELECT 1 FROM edc_pending.visits v2 WHERE v2.usubjid = edc_pending.visits.usubjid AND v2.planned_day > edc_pending.visits.planned_day)")
        for _, r in ctx.pick(df, count, "visits").iterrows():
            ctx.data.execute("DELETE FROM edc_pending.visits WHERE id = %s", (r.id,))
            ctx.record(self.kind, self.module, "edc.visits", r.id, r.visit, r.planned_day, None, r.usubjid, r.site_id)
        return 0


@register
class Duplicate(Injector):
    kind, module = "duplicate", "checks"
    COLS = "usubjid, site_id, test_code, value, unit, visit, measured_at, entered_at"

    def apply(self, ctx: InjectContext, count: int, params: dict) -> int:
        df = ctx.window("vitals", "id, usubjid, site_id")
        for _, r in ctx.pick(df, count, "vitals").iterrows():
            new_id = ctx.data.execute(f"INSERT INTO edc_pending.vitals ({self.COLS}) SELECT {self.COLS} FROM edc_pending.vitals WHERE id = %s RETURNING id", (r.id,)).fetchone()[0]
            ctx.used.setdefault("vitals", set()).add(new_id)
            ctx.record(self.kind, self.module, "edc.vitals", new_id, "row", r.id, "copy", r.usubjid, r.site_id)
        return 0


@register
class MissingField(Injector):
    kind, module = "missing_field", "checks"

    def apply(self, ctx: InjectContext, count: int, params: dict) -> int:
        df = ctx.window("lab", "id, usubjid, site_id, unit", "unit IS NOT NULL AND test_code IN ('ALT','AST','ALP','BILI','CREAT','HGB','PLAT')")
        for _, r in ctx.pick(df, count, "lab").iterrows():
            ctx.data.execute("UPDATE edc_pending.lab SET unit = NULL WHERE id = %s", (r.id,))
            ctx.data.execute("UPDATE lab_vendor.transfer SET unit = NULL WHERE accession_no = %s", (f"ACC-{r.id:07d}",))
            ctx.record(self.kind, self.module, "edc.lab", r.id, "unit", r.unit, None, r.usubjid, r.site_id)
        return 0
