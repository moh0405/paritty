"""Rule-based site risk score (spec §9.7): mean of capped (+/-4) robust z-scores of the site's features, mapped to 0-100."""
from __future__ import annotations

import math
from datetime import date

import numpy as np
from psycopg import Connection

from app.medical.signals import robust_z
from app.sites import anomaly, risk_model
from app.sites.kris import KRI_DEFS, KriValue, compute_kris, store_kris

CAP = 4.0
TWO_SIDED = {"ae_rate", "sae_rate"}      # unusually low or unusually high both deserve a look


def feature_table(kris: list[KriValue], anomalies: dict[str, list[anomaly.AnomalyResult]]) -> dict[str, dict[str, float]]:
    """site -> feature -> value. Features are shared by the rule score and the learned model (milestone 13)."""
    feats: dict[str, dict[str, float]] = {}
    for k in kris:
        if k.value is not None:
            feats.setdefault(k.site_id, {})[f"kri:{k.kri}"] = k.value
    for site, results in anomalies.items():
        for r in results:
            feats.setdefault(site, {})[f"anom:{r.test}"] = r.feature
    return feats


def rule_scores(feats: dict[str, dict[str, float]]) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Returns (score 0-100 per site, capped z per feature per site). Larger z = more unusual in the worrying direction."""
    names = sorted({n for f in feats.values() for n in f})
    zs: dict[str, dict[str, float]] = {s: {} for s in feats}
    for n in names:
        col = {s: f[n] for s, f in feats.items() if n in f}
        z = robust_z(col, min_scale=0.5 if n.startswith("anom:") else 1e-9)
        for s, v in z.items():
            v = abs(v) if n.removeprefix("kri:") in TWO_SIDED else v
            zs[s][n] = max(-CAP, min(CAP, v))
    scores = {s: (float(np.mean(list(z.values()))) + CAP) / (2 * CAP) * 100 if z else 50.0 for s, z in zs.items()}
    return scores, zs


def explain(kris: list[KriValue], anomalies: list[anomaly.AnomalyResult]) -> list[dict]:
    """Plain-English reasons to look: the data, the comparison group, the threshold and the value."""
    out = []
    for k in kris:
        if k.rag in ("red", "amber") and k.value is not None:
            d = KRI_DEFS[k.kri]
            comp = f"median across sites {k.comparator:.2f}" if k.comparator is not None else "other sites"
            out.append({"kind": "kri", "name": k.kri, "level": k.rag, "text": f"{d['label']} is {k.value:.2f} {d['unit']} ({comp}). Rule: {d['rule']}."})
    for a in anomalies:
        if a.flagged:
            out.append({"kind": "anomaly", "name": a.test, "level": "red", "text": a.explanation})
    return out


def compute_all(conn: Connection, today: date) -> dict:
    kris = compute_kris(conn, today)
    anoms = anomaly.run_all(conn, today)
    feats = feature_table(kris, anoms)
    scores, zs = rule_scores(feats)
    return {"kris": kris, "anomalies": anoms, "features": feats, "scores": scores, "z": zs, "model": risk_model.score_sites(zs)}


def store(conn: Connection, day: date, res: dict) -> None:
    import json
    store_kris(conn, day, res["kris"])
    by_site: dict[str, list[KriValue]] = {}
    for k in res["kris"]:
        by_site.setdefault(k.site_id, []).append(k)
    for site, score in res["scores"].items():
        model = res.get("model", {}).get(site)
        sig = {"explanations": explain(by_site.get(site, []), res["anomalies"].get(site, [])),
               "anomalies": [{"test": a.test, "flagged": a.flagged, "p": a.p_value, "statistic": a.statistic, "detail": a.detail} for a in res["anomalies"].get(site, [])],
               "z": res["z"].get(site, {}), "model": model.as_dict() if model else None}
        conn.execute("INSERT INTO ops.site_risk (sim_date, site_id, rule_score, model_score, signals) VALUES (%s,%s,%s,%s,%s) "
                     "ON CONFLICT (sim_date, site_id) DO UPDATE SET rule_score = EXCLUDED.rule_score, model_score = EXCLUDED.model_score, signals = EXCLUDED.signals",
                     (day, site, round(score, 2), model.score if model else None, json.dumps(sig, default=str)))
