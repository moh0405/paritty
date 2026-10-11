"""Reconciliation injectors: lab vendor feed and safety database differences."""
from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from app.evals.injectors.base import InjectContext, Injector, register
from app.recon.refs import usubjid_from_safety_ref
from app.seed.common import fetch_df

BILI_UMOL = 17.1
SYNONYMS: dict[str, list[str]] = {}


def _synonyms() -> dict[str, list[str]]:
    if not SYNONYMS:
        import csv
        from app.seed.common import PROTOCOL
        with open(PROTOCOL / "ae_synonyms.csv") as f:
            for row in csv.DictReader(f):
                SYNONYMS.setdefault(row["term_a"], []).append(row["term_b"])
    return SYNONYMS


def _lab_rows(ctx: InjectContext, where: str = "true") -> pd.DataFrame:
    return ctx.window("lab", "id, usubjid, site_id, value", f"value IS NOT NULL AND unit IS NOT NULL AND test_code IN ('ALT','AST','ALP','CREAT','HGB','PLAT','GLUC') AND {where}")


@register
class LabValueMismatch(Injector):
    kind, module = "lab_value_mismatch", "lab_recon"

    def apply(self, ctx, count, params):
        for _, r in ctx.pick(_lab_rows(ctx), count, "lab").iterrows():
            row = ctx.data.execute("SELECT id, result FROM lab_vendor.transfer WHERE accession_no = %s", (f"ACC-{r.id:07d}",)).fetchone()
            if row:
                new = round(float(row[1]) * (1 + float(ctx.rng.choice([-1, 1])) * float(ctx.rng.uniform(0.05, 0.3))), 2)
                ctx.data.execute("UPDATE lab_vendor.transfer SET result = %s WHERE id = %s", (str(new), row[0]))
                ctx.record(self.kind, self.module, "lab_vendor.transfer", row[0], "result", row[1], new, r.usubjid, r.site_id)
        return 0


@register
class LabUnitMismatch(Injector):
    kind, module = "lab_unit_mismatch", "lab_recon"

    def apply(self, ctx, count, params):
        for _, r in ctx.pick(_lab_rows(ctx), count, "lab").iterrows():
            row = ctx.data.execute("SELECT id, unit FROM lab_vendor.transfer WHERE accession_no = %s", (f"ACC-{r.id:07d}",)).fetchone()
            if row:
                new = str(ctx.rng.choice(["g/L", "mg/dL", "ukat/L"]))
                ctx.data.execute("UPDATE lab_vendor.transfer SET unit = %s WHERE id = %s", (new, row[0]))
                ctx.record(self.kind, self.module, "lab_vendor.transfer", row[0], "unit", row[1], new, r.usubjid, r.site_id)
        return 0


@register
class LabOneSided(Injector):
    kind, module = "lab_one_sided", "lab_recon"

    def apply(self, ctx, count, params):
        for i, (_, r) in enumerate(ctx.pick(_lab_rows(ctx), count, "lab").iterrows()):
            if i % 2 == 0:       # EDC has it, vendor does not
                row = ctx.data.execute("DELETE FROM lab_vendor.transfer WHERE accession_no = %s RETURNING id", (f"ACC-{r.id:07d}",)).fetchone()
                ctx.record(self.kind, self.module, "lab_vendor.transfer", row[0] if row else None, "edc_only", r.value, None, r.usubjid, r.site_id)
            else:                # vendor has it, EDC does not
                ctx.data.execute("DELETE FROM edc_pending.lab WHERE id = %s", (r.id,))
                ctx.record(self.kind, self.module, "edc.lab", r.id, "vendor_only", r.value, None, r.usubjid, r.site_id)
        return 0


@register
class StaleFeed(Injector):
    kind, module = "stale_feed", "lab_recon"

    def apply(self, ctx, count, params):
        w0 = ctx.today + timedelta(days=int(params.get("start_in_days", 10)))
        n = ctx.data.execute("UPDATE lab_vendor.transfer SET file_date = %s WHERE file_date >= %s AND file_date < %s",
                             (w0 + timedelta(days=10), w0, w0 + timedelta(days=10))).rowcount
        ctx.record(self.kind, self.module, "lab_vendor.transfer", None, f"{w0}..{w0 + timedelta(days=9)}", n, "late batch")
        return 0


class SaeInjector(Injector):
    """Common case selection: single-version safety cases that become available inside the run window."""
    module = "sae_recon"

    def cases(self, ctx: InjectContext) -> pd.DataFrame:
        df = fetch_df(ctx.data, "SELECT id, safetyreportid, subject_ref, causality, payload, available_on FROM safety.case_versions c WHERE version = 1 "
                                "AND NOT EXISTS (SELECT 1 FROM safety.case_versions d WHERE d.safetyreportid = c.safetyreportid AND d.version > 1) AND available_on > %s AND available_on <= %s",
                      (ctx.today, ctx.horizon))
        df = df[~df.safetyreportid.isin(ctx.used.setdefault("cases", set()))]
        df["payload"] = df.payload.map(lambda p: p if isinstance(p, dict) else json.loads(p))
        df["usubjid"] = df.subject_ref.map(usubjid_from_safety_ref)
        return df

    def take(self, ctx: InjectContext, count: int, pred=lambda row: True):
        df = self.cases(ctx)
        df = df[[bool(pred(r)) for _, r in df.iterrows()]]
        picked = ctx.pick(df, count, "cases_dummy")
        ctx.used["cases"].update(picked.safetyreportid)
        return picked

    def save(self, ctx, row, payload, causality=None):
        ctx.data.execute("UPDATE safety.case_versions SET payload = %s, causality = COALESCE(%s, causality) WHERE id = %s", (json.dumps(payload), causality, int(row.id)))

    def site(self, row) -> str | None:
        return row.usubjid.split("-")[1] if row.usubjid else None


@register
class SaeDateShift(SaeInjector):
    kind = "sae_date_shift"

    def apply(self, ctx, count, params):
        for _, r in self.take(ctx, count).iterrows():
            delta = int(params.get("delta", int(ctx.rng.choice([-1, 1])) * int(ctx.rng.integers(3, 11))))
            p = json.loads(json.dumps(r.payload))
            rx = p["patient"]["reaction"][0]
            old = rx["reactionstartdate"]
            rx["reactionstartdate"] = (pd.Timestamp(old) + timedelta(days=delta)).strftime("%Y%m%d")
            self.save(ctx, r, p)
            ctx.record(self.kind, self.module, "safety.case_versions", r.safetyreportid, "onset_delta_days", old, delta, r.usubjid, self.site(r))
        return 0


@register
class SaeSynonym(SaeInjector):
    kind = "sae_synonym"

    def apply(self, ctx, count, params):
        syn = _synonyms()
        for _, r in self.take(ctx, count, lambda row: row.payload["patient"]["reaction"][0]["reactionmeddrapt"] in syn).iterrows():
            p = json.loads(json.dumps(r.payload))
            old = p["patient"]["reaction"][0]["reactionmeddrapt"]
            new = str(ctx.rng.choice(syn[old]))
            p["patient"]["reaction"][0]["reactionmeddrapt"] = new
            self.save(ctx, r, p)
            ctx.record(self.kind, self.module, "safety.case_versions", r.safetyreportid, "reactionmeddrapt", old, new, r.usubjid, self.site(r))
        return 0


@register
class SaeCodedChange(SaeInjector):
    kind = "sae_coded_change"

    def apply(self, ctx, count, params):
        pool = sorted({c.payload["patient"]["reaction"][0]["reactionmeddrapt"] for _, c in fetch_cases(ctx).iterrows()})
        for _, r in self.take(ctx, count).iterrows():
            p = json.loads(json.dumps(r.payload))
            old = p["patient"]["reaction"][0]["reactionmeddrapt"]
            new = str(ctx.rng.choice([t for t in pool if t != old and t not in _synonyms().get(old, [])] or ["NAUSEA"]))
            p["patient"]["reaction"][0]["reactionmeddrapt"] = new
            self.save(ctx, r, p)
            ctx.record(self.kind, self.module, "safety.case_versions", r.safetyreportid, "reactionmeddrapt", old, new, r.usubjid, self.site(r))
        return 0


def fetch_cases(ctx: InjectContext) -> pd.DataFrame:
    df = fetch_df(ctx.data, "SELECT payload FROM safety.case_versions WHERE version = 1")
    df["payload"] = df.payload.map(lambda p: p if isinstance(p, dict) else json.loads(p))
    return df


@register
class SaeCausalityFlip(SaeInjector):
    kind = "sae_causality_flip"

    def apply(self, ctx, count, params):
        for _, r in self.take(ctx, count, lambda row: row.causality in ("Related", "Not related")).iterrows():
            new = "Not related" if r.causality == "Related" else "Related"
            self.save(ctx, r, r.payload, new)
            ctx.record(self.kind, self.module, "safety.case_versions", r.safetyreportid, "causality", r.causality, new, r.usubjid, self.site(r))
        return 0


@register
class SaeSeriousnessFlip(SaeInjector):
    kind = "sae_seriousness_flip"

    def apply(self, ctx, count, params):
        for _, r in self.take(ctx, count).iterrows():
            p = json.loads(json.dumps(r.payload))
            p["serious"] = "2"
            for k in [k for k in p if k.startswith("seriousness")]:
                p.pop(k)
            self.save(ctx, r, p)
            ctx.record(self.kind, self.module, "safety.case_versions", r.safetyreportid, "serious", "1", "2", r.usubjid, self.site(r))
        return 0


@register
class SaeMissingOutcome(SaeInjector):
    kind = "sae_missing_outcome"

    def apply(self, ctx, count, params):
        for _, r in self.take(ctx, count).iterrows():
            p = json.loads(json.dumps(r.payload))
            old = p["patient"]["reaction"][0].pop("reactionoutcome", None)
            self.save(ctx, r, p)
            ctx.record(self.kind, self.module, "safety.case_versions", r.safetyreportid, "reactionoutcome", old, None, r.usubjid, self.site(r))
        return 0


@register
class SaeEdcOnly(SaeInjector):
    kind = "sae_edc_only"

    def apply(self, ctx, count, params):
        for _, r in self.take(ctx, count).iterrows():
            ctx.data.execute("DELETE FROM safety.case_versions WHERE safetyreportid = %s", (r.safetyreportid,))
            ctx.record(self.kind, self.module, "safety.case_versions", r.safetyreportid, "case", "present", "absent", r.usubjid, self.site(r))
        return 0


@register
class SaeSafetyOnly(SaeInjector):
    kind = "sae_safety_only"

    def apply(self, ctx, count, params):
        for _, r in self.take(ctx, count).iterrows():
            p = r.payload["patient"]["reaction"][0]
            ae = ctx.data.execute("SELECT id FROM edc_pending.ae WHERE usubjid = %s AND serious AND term_coded = %s ORDER BY id LIMIT 1", (r.usubjid, p["reactionmeddrapt"])).fetchone()
            if ae:
                ctx.data.execute("DELETE FROM edc_pending.ae WHERE id = %s", (ae[0],))
                ctx.record(self.kind, self.module, "edc.ae", ae[0], r.safetyreportid, "present", "absent", r.usubjid, self.site(r))
        return 0


@register
class SaeDeathMismatch(SaeInjector):
    kind = "sae_death_mismatch"

    def apply(self, ctx, count, params):
        for _, r in self.take(ctx, count, lambda row: row.payload["patient"]["reaction"][0].get("reactionoutcome") != "5").iterrows():
            p = json.loads(json.dumps(r.payload))
            p["seriousnessdeath"] = "1"
            p["patient"]["reaction"][0]["reactionoutcome"] = "5"
            self.save(ctx, r, p)
            ctx.record(self.kind, self.module, "safety.case_versions", r.safetyreportid, "death", "0", "1", r.usubjid, self.site(r))
        return 0
