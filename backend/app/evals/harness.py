"""Eval run loop (spec §12): scenario run -> fork -> inject -> advance N days -> score as eval_admin -> metrics -> always delete the fork."""
from __future__ import annotations

import json
import secrets
import sys
import time
import traceback
import uuid

import numpy as np
import pandas as pd
import psycopg

from app.config import get_settings
from app.db.target import use_database
from app.evals import causality_eval, protocol_eval, scorer
from app.evals.fork_manager import Fork, get_fork_manager
from app.evals.injectors import InjectContext, run_injections
from app.evals.scenarios import Scenario, load
from app.sim.clock import TrialClock
from app.sim.daily_cycle import DailyCycle


def _advance(app: psycopg.Connection, days: int) -> None:
    cycle = DailyCycle(app)
    for _ in range(days):
        cycle.run(auto_approve=True)
        app.commit()


def run_on_fork(fork: Fork, scn: Scenario, seed: int | None, run_id: str | None) -> tuple[scorer.Observations, pd.DataFrame, pd.DataFrame, dict]:
    use_database(fork.app_url, fork.eval_url)
    done: dict[str, int] = {}
    with psycopg.connect(fork.app_url) as app, psycopg.connect(fork.eval_url) as key:
        today = TrialClock(app).today()
        if scn.injections and seed is not None:
            from datetime import timedelta
            ctx = InjectContext(app, key, np.random.default_rng(seed), run_id, today, today + timedelta(days=scn.advance_days))
            done = run_injections(ctx, scn.injections)
            app.commit()
            key.commit()
        _advance(app, scn.advance_days)
        obs = scorer.observe(app, TrialClock(app).today())
        planted = pd.read_sql("SELECT * FROM answer_key.planted WHERE scenario_run_id = %s", key, params=(run_id,)) if run_id else pd.DataFrame()
        truth = pd.read_sql("SELECT site_id, personality FROM answer_key.site_personality", key)
        obs.protocol = protocol_eval.score(app, key)
        obs.causality = causality_eval.score(app, key, TrialClock(app).today())
        app.commit()
        obs.xtruth = {(sys_, sid): canon for sys_, sid, canon in key.execute("SELECT system, source_id, canonical_id FROM answer_key.crosswalk_truth")}
    return obs, planted, truth, done


def run_scenario(name: str, repeats: int = 1, on_event=print) -> list[str]:
    scn = load(name)
    s = get_settings()
    main_url, main_app = s.eval_admin_url, s.database_url
    fm = get_fork_manager()
    run_ids = []
    for rep in range(repeats):
        run_id = str(uuid.uuid4())
        seed = secrets.randbelow(2 ** 31)
        run_ids.append(run_id)
        with psycopg.connect(main_url) as main:
            main.execute("INSERT INTO eval.scenario_runs (id, scenario, seed, fork_name, model, prompt_version, status) VALUES (%s,%s,%s,%s,%s,%s,'running')",
                         (run_id, scn.name, seed, f"fork_{run_id[:8]}", scn.model, scn.prompt_version))
            main.commit()
        forks: list[Fork] = []
        status, detail = "done", None
        try:
            control = None
            if scn.baseline and scn.injections:
                on_event(f"[{scn.name} {rep + 1}/{repeats}] control fork: {scn.advance_days} days without injections")
                cf = fm.create(f"fork_{run_id[:8]}_ctl")
                forks.append(cf)
                control = run_on_fork(cf, scn, None, None)[0]
                use_database(main_app, main_url)
            on_event(f"[{scn.name} {rep + 1}/{repeats}] injected fork")
            f = fm.create(f"fork_{run_id[:8]}")
            forks.append(f)
            obs, planted, truth, done = run_on_fork(f, scn, seed, run_id)
            use_database(main_app, main_url)
            metrics = scorer.score(planted, truth, obs, control, f.seconds)
            with psycopg.connect(main_url) as main:
                for m in metrics:
                    main.execute("INSERT INTO eval.metrics (scenario_run_id, module, metric, value, detail) VALUES (%s,%s,%s,%s,%s)",
                                 (run_id, m.module, m.metric, m.value, json.dumps({**m.detail, **({"injected": done} if m.metric == "fork_seconds" else {})})))
                for r in planted.itertuples():
                    main.execute("INSERT INTO answer_key.planted (scenario_run_id, kind, module, usubjid, site_id, src_table, src_pk, field, original, injected) "
                                 "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (run_id, r.kind, r.module, r.usubjid, r.site_id, r.src_table, r.src_pk, r.field, r.original, r.injected))
                main.commit()
        except Exception as exc:
            status, detail = "failed", f"{type(exc).__name__}: {exc}"
            traceback.print_exc(file=sys.stderr)
        finally:
            use_database(main_app, main_url)
            for f in forks:
                try:
                    fm.delete(f)
                except Exception as exc:
                    print(f"warning: could not delete fork {f.name}: {exc}", file=sys.stderr)
            with psycopg.connect(main_url) as main:
                main.execute("UPDATE eval.scenario_runs SET status = %s, fork_seconds = %s, finished_at = now() WHERE id = %s", (status, forks[-1].seconds if forks else None, run_id))
                if detail:
                    main.execute("INSERT INTO eval.metrics (scenario_run_id, module, metric, value, detail) VALUES (%s,'system','error',0,%s)", (run_id, json.dumps({"error": detail})))
                main.commit()
        on_event(f"[{scn.name}] run {run_id[:8]} {status}")
    return run_ids
