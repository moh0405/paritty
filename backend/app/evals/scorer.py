"""Score a finished fork against its planted truth (spec §12). Runs as eval_admin. Findings that also appear on the un-injected
control fork are excluded from false positives; recall counts only items planted by this run."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import psycopg

from app.medical.service import MedicalService
from app.sites.risk import compute_all

SAE_SPECS = {"sae_onset", "sae_term", "sae_seriousness", "sae_causality", "sae_outcome", "sae_death", "sae_safety_only", "sae_fatal_one_sided", "chk_22"}
LAB_SPECS = {"chk_24", "chk_25", "chk_26", "lab_stale_feed"}
EXPECT_LAB = {"lab_value_mismatch": {"chk_24"}, "lab_unit_mismatch": {"chk_26"}, "lab_one_sided": {"chk_25"}, "stale_feed": {"lab_stale_feed"}}
EXPECT_SAE = {
    "sae_date_shift": {"sae_onset"}, "sae_synonym": {"sae_term"}, "sae_coded_change": {"sae_term"}, "sae_causality_flip": {"sae_causality"},
    "sae_seriousness_flip": {"sae_seriousness"}, "sae_missing_outcome": {"sae_outcome"}, "sae_death_mismatch": {"sae_death"},
    "sae_edc_only": {"chk_22", "sae_fatal_one_sided"}, "sae_safety_only": {"sae_safety_only", "sae_fatal_one_sided"},
}
CHECK_KINDS = {"impossible_value", "date_order", "unit_mixup", "missing_visit", "duplicate", "missing_field"}


@dataclass
class Metric:
    module: str
    metric: str
    value: float
    detail: dict = field(default_factory=dict)


@dataclass
class Observations:
    day: date
    check_keys: set = field(default_factory=set)            # (src_table, src_pk) of SQL-check failures
    visit_keys: set = field(default_factory=set)            # (usubjid, visit) of missing-visit failures
    sae_pairs: set = field(default_factory=set)             # (usubjid, spec)
    lab_keys: set = field(default_factory=set)              # (check_id, usubjid)
    hys: set = field(default_factory=set)
    creep_sites: set = field(default_factory=set)
    cluster: set = field(default_factory=set)               # (site, term)
    link_labs: set = field(default_factory=set)
    site_scores: dict = field(default_factory=dict)
    site_model_scores: dict = field(default_factory=dict)   # learned model, 0-100 (empty when the model is not trained)
    xwalk: dict = field(default_factory=dict)               # (system, source_id) -> canonical (None = left for a person)
    xtruth: dict = field(default_factory=dict)              # filled from the answer key by the harness (eval only)
    protocol: dict = field(default_factory=dict)            # eligibility assistant scores, computed by the harness (eval only)
    causality: dict = field(default_factory=dict)
    claims: dict = field(default_factory=dict)
    llm: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)


def observe(app: psycopg.Connection, day: date) -> Observations:
    o = Observations(day)
    for check, usubjid, table, pk in app.execute("SELECT check_id, usubjid, src_table, src_pk FROM ops.check_failures"):
        if check in SAE_SPECS:
            o.sae_pairs.add((usubjid, check))
        elif check in LAB_SPECS:
            o.lab_keys.add((check, usubjid))
        elif "|" in str(pk):
            o.visit_keys.add((usubjid, pk.split("|")[1]))
        else:
            o.check_keys.add((table, str(pk)))
    for system, sid, canon in app.execute("SELECT system, source_id, canonical_subject FROM hub.subject_xwalk WHERE status <> 'rejected' UNION ALL SELECT system, source_id, canonical_site FROM hub.site_xwalk WHERE status <> 'rejected'"):
        o.xwalk[(system, sid)] = canon
    svc = MedicalService(app)
    o.hys = {h.usubjid for h in svc.hys_cases()}
    o.creep_sites = {c.site_id for c in svc.creep()}
    o.cluster = {(c.site_id, c.term) for c in svc.clusters()}
    o.link_labs = {l.lab.id for l in svc.links()}
    risk = compute_all(app, day)
    o.site_scores = risk["scores"]
    o.site_model_scores = {s: m.score for s, m in risk["model"].items()}
    o.claims = dict(app.execute("SELECT c->>'status', count(*) FROM ai.findings f, jsonb_array_elements(f.body->'claims') c GROUP BY 1").fetchall())
    r = app.execute("SELECT count(*), coalesce(sum(input_tokens),0), coalesce(sum(output_tokens),0), coalesce(avg(latency_ms) FILTER (WHERE NOT cache_hit),0) FROM ai.llm_calls").fetchone()
    o.llm = {"calls": r[0], "input_tokens": int(r[1]), "output_tokens": int(r[2]), "avg_latency_ms": float(r[3])}
    o.counts = {"queries": app.execute("SELECT count(*) FROM ops.queries").fetchone()[0], "failures": app.execute("SELECT count(*) FROM ops.check_failures").fetchone()[0]}
    return o


def prf(tp: int, predicted: int, actual: int) -> tuple[float, float, float]:
    p, r = (tp / predicted if predicted else 0.0), (tp / actual if actual else 0.0)
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def score(planted: pd.DataFrame, site_truth: pd.DataFrame, obs: Observations, control: Observations | None, fork_seconds: float) -> list[Metric]:
    ctl = control or Observations(obs.day)
    out: list[Metric] = []

    # ---- edit checks -----------------------------------------------------------------------------------
    pc = planted[planted.kind.isin(CHECK_KINDS)]
    if len(pc):
        hit = [((r.usubjid, r.field) in obs.visit_keys) if r.kind == "missing_visit" else ((r.src_table, str(r.src_pk)) in obs.check_keys) for r in pc.itertuples()]
        pc = pc.assign(hit=hit)
        planted_keys = {(r.src_table, str(r.src_pk)) for r in pc.itertuples() if r.kind != "missing_visit"}
        planted_visits = {(r.usubjid, r.field) for r in pc.itertuples() if r.kind == "missing_visit"}
        predicted = (obs.check_keys - ctl.check_keys) | {("visit", f"{u}|{v}") for u, v in obs.visit_keys - ctl.visit_keys}
        tp_pred = len((obs.check_keys - ctl.check_keys) & planted_keys) + len((obs.visit_keys - ctl.visit_keys) & planted_visits)
        p, r, f = prf(tp_pred, len(predicted), len(pc))
        out += [Metric("checks", "precision", p, {"predicted_new": len(predicted)}), Metric("checks", "recall", sum(hit) / len(pc), {"planted": len(pc)}), Metric("checks", "f1", f)]
        for kind, g in pc.groupby("kind"):
            out.append(Metric("checks", f"recall_{kind}", float(g.hit.mean()), {"planted": len(g)}))

    # ---- SAE reconciliation -----------------------------------------------------------------------------
    ps = planted[planted.kind.isin(EXPECT_SAE)]
    if len(ps):
        rows = []
        for r in ps.itertuples():
            acceptable = r.kind == "sae_synonym" or (r.kind == "sae_date_shift" and abs(int(r.injected)) <= 1)
            flagged = any((r.usubjid, s) in obs.sae_pairs for s in EXPECT_SAE[r.kind])
            rows.append((r.kind, acceptable, flagged))
        act = [x for x in rows if not x[1]]
        acc = [x for x in rows if x[1]]
        planted_pairs = {(r.usubjid, s) for r in ps.itertuples() for s in EXPECT_SAE[r.kind]}
        new_pairs = obs.sae_pairs - ctl.sae_pairs
        recall = sum(x[2] for x in act) / len(act) if act else 0.0
        precision = len(new_pairs & planted_pairs) / len(new_pairs) if new_pairs else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out += [Metric("sae_recon", "recall", recall, {"actionable_planted": len(act)}), Metric("sae_recon", "precision", precision, {"flags": len(new_pairs)}),
                Metric("sae_recon", "f1", f1)]
        if acc:
            out.append(Metric("sae_recon", "acceptable_handled_correctly", sum(not x[2] for x in acc) / len(acc), {"planted_acceptable": len(acc)}))
        out.append(Metric("sae_recon", "acceptable_vs_actionable_accuracy", (sum(x[2] for x in act) + sum(not x[2] for x in acc)) / len(rows)))
        syn = [x for x in rows if x[0] == "sae_synonym"]
        if syn:
            out.append(Metric("sae_recon", "synonym_false_positive_rate", sum(x[2] for x in syn) / len(syn), {"n": len(syn)}))

    # ---- lab reconciliation ----------------------------------------------------------------------------
    pl = planted[planted.kind.isin(EXPECT_LAB)]
    if len(pl):
        hits = []
        for r in pl.itertuples():
            hits.append(any((c, r.usubjid) in obs.lab_keys for c in EXPECT_LAB[r.kind]))
        pl = pl.assign(hit=hits)
        truth_pairs = {(c, r.usubjid) for r in pl.itertuples() for c in EXPECT_LAB[r.kind]}
        new = {k for k in obs.lab_keys - ctl.lab_keys if k[0] != "lab_stale_feed"}
        out += [Metric("lab_recon", "recall", float(pl.hit.mean()), {"planted": len(pl)}),
                Metric("lab_recon", "precision", len(new & truth_pairs) / len(new) if new else 0.0, {"new_flags": len(new)})]
        for kind, g in pl.groupby("kind"):
            out.append(Metric("lab_recon", f"recall_{kind}", float(g.hit.mean()), {"planted": len(g)}))

    # ---- medical signals --------------------------------------------------------------------------------
    for kind, label, got, key in (("hys_law_plant", "hys_law", obs.hys, lambda r: r.usubjid), ("site_creep", "site_creep", obs.creep_sites, lambda r: r.site_id),
                                  ("ae_lab_link", "ae_lab_link", obs.link_labs, lambda r: int(r.src_pk))):
        pm = planted[planted.kind == kind]
        if len(pm):
            truth = {key(r) for r in pm.itertuples()}
            new = got - (ctl.hys if kind == "hys_law_plant" else ctl.creep_sites if kind == "site_creep" else ctl.link_labs)
            out += [Metric("medical", f"{label}_recall", len(truth & got) / len(truth), {"planted": len(truth)}),
                    Metric("medical", f"{label}_precision", len(truth & new) / len(new) if new else 0.0, {"new_flags": len(new)})]
    pc2 = planted[planted.kind == "rare_ae_cluster"]
    if len(pc2):
        sites = {r.site_id for r in pc2.itertuples()}
        out.append(Metric("medical", "rare_ae_cluster_recall", len({s for s, _ in obs.cluster} & sites) / len(sites), {"planted_sites": len(sites)}))

    # ---- sites (rule score top-k) -------------------------------------------------------------------------
    if obs.site_scores and len(site_truth):
        truth = set(site_truth[site_truth.personality != "normal"].site_id)
        ranked = sorted(obs.site_scores, key=obs.site_scores.get, reverse=True)
        k = len(truth)
        top = set(ranked[:k])
        out += [Metric("sites", "rule_precision_at_k", len(top & truth) / k, {"k": k}), Metric("sites", "rule_recall_at_k", len(top & truth) / k, {"k": k}),
                Metric("sites", "rule_recall_at_k_plus_5", len(set(ranked[:k + 5]) & truth) / k)]
        if obs.site_model_scores:      # the learned model on the same top-k question, to compare with the rule score
            by_model = sorted(obs.site_model_scores, key=obs.site_model_scores.get, reverse=True)
            out += [Metric("sites", "model_precision_at_k", len(set(by_model[:k]) & truth) / k, {"k": k}),
                    Metric("sites", "model_recall_at_k", len(set(by_model[:k]) & truth) / k, {"k": k}),
                    Metric("sites", "model_recall_at_k_plus_5", len(set(by_model[:k + 5]) & truth) / k)]
        inj = {r.site_id for r in planted[planted.kind == "site_personality"].itertuples()}
        if inj:
            out.append(Metric("sites", "injected_site_recall_at_k_plus_5", len(set(ranked[:k + 5]) & inj) / len(inj), {"injected": len(inj)}))

    # ---- crosswalk (hub) -------------------------------------------------------------------------------
    if obs.xtruth and obs.xwalk:
        seen = {k: v for k, v in obs.xwalk.items() if (("ctms_site" if k[0] == "ctms" else k[0]), k[1]) in obs.xtruth}
        truth = lambda k: obs.xtruth[(("ctms_site" if k[0] == "ctms" else k[0]), k[1])]  # noqa: E731
        mapped = {k: v for k, v in seen.items() if v is not None}
        correct = sum(truth(k) == v for k, v in mapped.items())
        with_truth = [k for k in seen if truth(k) is not None]
        out += [Metric("hub", "crosswalk_precision", correct / len(mapped) if mapped else 0.0, {"mapped": len(mapped)}),
                Metric("hub", "crosswalk_recall", sum(seen[k] == truth(k) for k in with_truth) / len(with_truth) if with_truth else 0.0, {"identifiers": len(with_truth)})]
        none_truth = [k for k in seen if truth(k) is None]
        if none_truth:
            out.append(Metric("hub", "crosswalk_unmatched_correct", sum(seen[k] is None for k in none_truth) / len(none_truth), {"identifiers": len(none_truth)}))
        noisy = planted[planted.kind == "xwalk_noise"]
        if len(noisy):
            keys = [(r.field, r.injected) for r in noisy.itertuples()]
            out.append(Metric("hub", "noise_resolved_correctly", sum(obs.xwalk.get(k) == truth(k) for k in keys if k in obs.xwalk) / len(keys), {"noisy_identifiers": len(keys)}))
            out.append(Metric("hub", "noise_left_for_review", sum(obs.xwalk.get(k, 'x') is None for k in keys) / len(keys)))

    # ---- protocol assistant -----------------------------------------------------------------------------
    if obs.protocol:
        out += [Metric("protocol", "eligibility_accuracy", obs.protocol["accuracy"], {"questions": obs.protocol["n"]}),
                Metric("protocol", "escalation_precision", obs.protocol["escalation_precision"]), Metric("protocol", "escalation_recall", obs.protocol["escalation_recall"])]

    # ---- causality --------------------------------------------------------------------------------------
    if obs.causality:
        c = obs.causality
        out += [Metric("causality", "cases_assessed", float(c["assessed"])), Metric("causality", "ai_assessed", float(c["ai_assessed"])),
                Metric("causality", "escalated_share", c["escalated_share"])]
        if "agreement" in c:
            out += [Metric("causality", "agreement", c["agreement"], {"n": c["ai_assessed"]}), Metric("causality", "kappa", c["kappa"], {"n": c["ai_assessed"]})]

    # ---- grounding, cost and speed -------------------------------------------------------------------------
    total = sum(obs.claims.values())
    out += [Metric("system", "grounding_rate", obs.claims.get("verified", 0) / total if total else 0.0, {"claims": total}),
            Metric("system", "blocked_claims", float(total - obs.claims.get("verified", 0))),
            Metric("system", "llm_calls", float(obs.llm["calls"])), Metric("system", "llm_input_tokens", float(obs.llm["input_tokens"])),
            Metric("system", "llm_output_tokens", float(obs.llm["output_tokens"])), Metric("system", "llm_avg_latency_ms", obs.llm["avg_latency_ms"]),
            Metric("system", "fork_seconds", fork_seconds), Metric("system", "queries_opened", float(obs.counts["queries"]))]
    return out
