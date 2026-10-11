"""Metrics tables for the CLI and API."""
from __future__ import annotations

import psycopg

from app.config import get_settings


def run_metrics(run_id: str) -> dict[str, list[dict]]:
    with psycopg.connect(get_settings().eval_admin_url) as c:
        rows = c.execute("SELECT module, metric, value, detail FROM eval.metrics WHERE scenario_run_id = %s ORDER BY module, metric", (run_id,)).fetchall()
    out: dict[str, list[dict]] = {}
    for module, metric, value, detail in rows:
        out.setdefault(module, []).append({"metric": metric, "value": value, "detail": detail})
    return out


def format_table(run_id: str) -> str:
    lines = []
    for module, ms in run_metrics(run_id).items():
        lines.append(f"\n[{module}]")
        for m in ms:
            v = m["value"]
            lines.append(f"  {m['metric']:<38} {v:>10.3f}" if abs(v) < 1000 else f"  {m['metric']:<38} {v:>10.0f}")
    return "\n".join(lines)
