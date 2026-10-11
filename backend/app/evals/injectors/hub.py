"""Crosswalk-noise injector: external systems start sending identifiers in slightly different forms."""
from __future__ import annotations

import re

from app.evals.injectors.base import InjectContext, Injector, register
from app.hub.normalize import parse_lab_ref, parse_safety_ref


def noisy_lab(ref: str, variant: int) -> str:
    m = re.match(r"^PT(\d+)-(\d+)$", ref)
    site, num = m.group(1), m.group(2)
    return [f"PT{site}-{num.replace('0', 'O', 1)}", f"pt{site}-{num}", f"PT {site} - {num}", f"PT{site}{num}"][variant % 4]


def noisy_safety(ref: str, variant: int) -> str:
    m = re.match(r"^SUBJ (\d+) / SITE (\d+)$", ref)
    num, site = m.group(1), m.group(2)
    return [f"SUBJ {num}/SITE {site}", f"Subj {num} / Site {site}", f"SUBJ {num} SITE {site}"][variant % 3]


@register
class XwalkNoise(Injector):
    kind, module = "xwalk_noise", "hub"

    def apply(self, ctx: InjectContext, count: int, params: dict) -> int:
        rows = ctx.data.execute("SELECT DISTINCT patient_ref FROM lab_vendor.transfer WHERE NOT released AND file_date > %s AND file_date <= %s AND patient_ref ~ '^PT[0-9]+-[0-9]+$'",
                                (ctx.today, ctx.horizon)).fetchall()
        refs = [r[0] for r in rows]
        ctx.rng.shuffle(refs)
        n_lab = max(1, (count + 1) // 2)
        for i, ref in enumerate(refs[:n_lab]):
            new = noisy_lab(ref, i)
            canonical = parse_lab_ref(ref).usubjid
            ctx.data.execute("UPDATE lab_vendor.transfer SET patient_ref = %s WHERE patient_ref = %s AND NOT released", (new, ref))
            self._record(ctx, "lab_vendor", ref, new, canonical)
        cases = [r[0] for r in ctx.data.execute("SELECT DISTINCT subject_ref FROM safety.case_versions WHERE available_on > %s AND available_on <= %s", (ctx.today, ctx.horizon))]
        ctx.rng.shuffle(cases)
        for i, ref in enumerate(cases[: max(0, count - n_lab)]):
            new = noisy_safety(ref, i)
            ctx.data.execute("UPDATE safety.case_versions SET subject_ref = %s WHERE subject_ref = %s AND available_on > %s", (new, ref, ctx.today))
            self._record(ctx, "safety", ref, new, parse_safety_ref(ref).usubjid)
        return 0

    def _record(self, ctx: InjectContext, system: str, original: str, noisy: str, canonical: str) -> None:
        ctx.key.execute("INSERT INTO answer_key.crosswalk_truth (system, source_id, canonical_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (system, noisy, canonical))
        ctx.record(self.kind, self.module, f"{system}", None, system, original, noisy, canonical, canonical.split("-")[1])
