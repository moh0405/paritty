"""Forecast backtest (spec §9.8): on a fork, advance N days, note the stored forecast, advance to completion, compare with the realised lock."""
from __future__ import annotations

from datetime import date, timedelta

import psycopg

from app.evals.scorer import Metric
from app.forecast.montecarlo import LOCK_PROCEDURE_DAYS

SETTLE_DAYS = 60            # after the last staged data enters, let queries settle for this long
CAP_DAYS = 560              # never advance more than this many simulated days in total
CHECKPOINT_EVERY = 30


def realised_ready_date(app: psycopg.Connection) -> date:
    """The date the last piece of work finished: last data entry, last subject final status, last query closed."""
    last_entry = app.execute("SELECT greatest((SELECT max(entered_at) FROM edc.ae), (SELECT max(entered_at) FROM edc.lab), (SELECT max(entered_at) FROM edc.vitals), "
                             "(SELECT max(entered_at) FROM edc.visits))").fetchone()[0]
    last_final = app.execute("SELECT max(apply_on) FROM edc_pending.subject_updates WHERE applied").fetchone()[0]
    last_closed = app.execute("SELECT max(closed_on) FROM ops.queries").fetchone()[0]
    return max(d for d in (last_entry, last_final, last_closed) if d)


def advance_to_completion(app: psycopg.Connection, cycle, already: int) -> int:
    """Run days until all staged data is released and the queries have had time to settle. Returns the number of extra days run."""
    extra, settled = 0, 0
    while already + extra < CAP_DAYS and settled < SETTLE_DAYS:
        cycle.run(auto_approve=True)
        app.commit()
        extra += 1
        pending = app.execute("SELECT (SELECT count(*) FROM edc_pending.ae) + (SELECT count(*) FROM edc_pending.lab) + (SELECT count(*) FROM edc_pending.vitals) "
                              "+ (SELECT count(*) FROM edc_pending.visits)").fetchone()[0]
        settled = settled + 1 if pending == 0 else 0
    return extra


def checkpoint_errors(app: psycopg.Connection, first_day: date, actual: date) -> list[dict]:
    rows = app.execute("SELECT sim_date, p10, p50, p90 FROM ops.lock_forecasts WHERE sim_date >= %s ORDER BY sim_date", (first_day,)).fetchall()
    out = []
    for i, (d, p10, p50, p90) in enumerate(rows):
        if i % CHECKPOINT_EVERY == 0 and d < actual:
            out.append({"forecast_date": str(d), "p10": str(p10), "p50": str(p50), "p90": str(p90), "days_before_lock": (actual - d).days,
                        "error_days": (p50 - actual).days, "covered": bool(p10 <= actual <= p90)})
    return out


def metrics(app: psycopg.Connection, forecast_day: date, advance_days: int, cycle) -> tuple[list[Metric], list[dict]]:
    f = app.execute("SELECT p10, p50, p90 FROM ops.lock_forecasts WHERE sim_date = %s", (forecast_day,)).fetchone()
    advance_to_completion(app, cycle, advance_days)
    ready = realised_ready_date(app)
    actual = ready + timedelta(days=LOCK_PROCEDURE_DAYS)
    checkpoints = checkpoint_errors(app, forecast_day, actual)
    p10, p50, p90 = f
    out = [Metric("forecast", "abs_error_days", float(abs((p50 - actual).days)), {"forecast_day": str(forecast_day), "p50": str(p50), "actual_lock": str(actual)}),
           Metric("forecast", "bias_days", float((p50 - actual).days), {"positive_means_forecast_too_late": True}),
           Metric("forecast", "p10_p90_covered", 1.0 if p10 <= actual <= p90 else 0.0, {"p10": str(p10), "p90": str(p90)}),
           Metric("forecast", "actual_lock_study_day", float((actual - app.execute("SELECT study_start FROM ops.sim_clock").fetchone()[0]).days)),
           Metric("forecast", "checkpoints", float(len(checkpoints)), {"rows": checkpoints})]
    if checkpoints:
        out.append(Metric("forecast", "mean_abs_error_over_checkpoints_days", sum(abs(c["error_days"]) for c in checkpoints) / len(checkpoints)))
        out.append(Metric("forecast", "coverage_over_checkpoints", sum(c["covered"] for c in checkpoints) / len(checkpoints)))
    return out, checkpoints
