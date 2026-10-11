import subprocess
import sys
from pathlib import Path
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import jobs
from app.config import get_settings
from app.deps import Caller, get_caller
from app.evals import report
from app.evals.scenarios import list_scenarios

router = APIRouter(prefix="/eval", tags=["evals"])
BACKEND = Path(__file__).resolve().parents[3]


class RunIn(BaseModel):
    scenario: str
    repeats: int = Field(1, ge=1, le=10)


def _conn() -> psycopg.Connection:
    return psycopg.connect(get_settings().eval_admin_url)     # eval schema only: aggregate metrics, no patient data


@router.get("/scenarios")
def scenarios() -> list[dict]:
    return list_scenarios()


@router.post("/runs", status_code=202)
def start_run(body: RunIn, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    if body.scenario not in {s["name"] for s in list_scenarios()}:
        raise HTTPException(404, "unknown scenario")

    def work(progress):
        proc = subprocess.run([sys.executable, "-W", "ignore", "-m", "app.evals.run", "--scenario", body.scenario, "--repeats", str(body.repeats)],
                              cwd=BACKEND, capture_output=True, text=True)
        progress(body.repeats, {"exit": proc.returncode})
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-600:])
        return {"output": proc.stdout[-4000:]}
    try:
        return {"job_id": jobs.start("eval.run", body.repeats, work, exclusive="eval")}
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@router.get("/runs")
def runs(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT id, scenario, seed, model, prompt_version, status, started_at, finished_at, fork_seconds FROM eval.scenario_runs ORDER BY started_at DESC LIMIT %s", (min(limit, 200),)).fetchall()
        head = {}
        for rid, module, metric, value in c.execute("SELECT scenario_run_id, module, metric, value FROM eval.metrics WHERE (module, metric) IN "
                                                    "(('checks','recall'),('checks','precision'),('sae_recon','recall'),('sae_recon','precision'),('medical','hys_law_recall'),"
                                                    "('sites','rule_recall_at_k'),('system','grounding_rate'),('forecast','abs_error_days'),('lab_recon','recall'))"):
            head.setdefault(str(rid), {})[f"{module}.{metric}"] = value
    return [{"id": str(r[0]), "scenario": r[1], "seed": r[2], "model": r[3], "prompt_version": r[4], "status": r[5], "started_at": r[6], "finished_at": r[7],
             "fork_seconds": r[8], "headline": head.get(str(r[0]), {})} for r in rows]


@router.get("/runs/compare")
def compare(ids: str) -> dict:
    run_ids = [i for i in ids.split(",") if i][:6]
    table: dict[str, dict[str, float]] = {}
    for rid in run_ids:
        for module, ms in report.run_metrics(rid).items():
            for m in ms:
                table.setdefault(f"{module}.{m['metric']}", {})[rid] = m["value"]
    return {"runs": run_ids, "metrics": table}


@router.get("/compare")
def compare_alias(ids: str) -> dict:
    return compare(ids)


@router.get("/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    with _conn() as c:
        r = c.execute("SELECT id, scenario, seed, model, prompt_version, status, started_at, finished_at, fork_seconds FROM eval.scenario_runs WHERE id = %s", (run_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "unknown run")
        planted = dict(c.execute("SELECT kind, count(*) FROM answer_key.planted WHERE scenario_run_id = %s GROUP BY 1", (run_id,)).fetchall())
    return {"id": str(r[0]), "scenario": r[1], "seed": r[2], "model": r[3], "prompt_version": r[4], "status": r[5], "started_at": r[6], "finished_at": r[7],
            "fork_seconds": r[8], "planted": planted, "metrics": report.run_metrics(run_id)}


@router.post("/runs/{run_id}/summary")
def summary(run_id: str, caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    """A plain-English summary of a run whose every claim cites the metric rows it reports (spec §9.12)."""
    from app.db.connection import get_pool
    from app.evals.summary import EvalSummarizer
    from app.sim.clock import TrialClock
    with get_pool().connection() as conn:
        try:
            return EvalSummarizer(conn).summarize(run_id, TrialClock(conn).today())
        except KeyError:
            raise HTTPException(404, "unknown run")
