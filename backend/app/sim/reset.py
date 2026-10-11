"""Golden snapshot + reset (`make reset`, POST /sim/reset). The snapshot lives in schema `golden`."""
from __future__ import annotations

from datetime import timedelta

from psycopg import Connection

from app.config import get_settings
from app.sim.constants import STUDY_START
from app.sim.ingestor import release_through

EDC_TABLES = ["sites", "subjects", "ae", "lab", "vitals", "visits", "exposure", "conmeds", "medical_history"]
RUNTIME_TABLES = [
    "ops.check_failures", "ops.queries", "ops.query_events", "ops.site_responses", "ops.digests", "ops.kri_values",
    "ops.site_risk", "ops.lock_forecasts", "ops.issues", "ops.drafts", "ops.escalations", "ops.sim_state",
    "ai.findings", "ai.citations", "ai.verifications", "ai.term_decisions", "ai.causality_assessments", "ai.llm_calls",
    "audit.log", "hub.dq_results", "mock_safety.inbox",
]

def snapshot(conn: Connection) -> None:
    """Copy the fully seeded EDC (released + staged) and subject updates into `golden`."""
    for t in EDC_TABLES + ["subject_updates"]:
        conn.execute(f"DROP TABLE IF EXISTS golden.{t}")
    for t in EDC_TABLES:
        conn.execute(f"CREATE TABLE golden.{t} AS SELECT * FROM edc.{t}")
        if t != "sites":
            conn.execute(f"INSERT INTO golden.{t} SELECT * FROM edc_pending.{t}")
    conn.execute("CREATE TABLE golden.subject_updates AS SELECT * FROM edc_pending.subject_updates")
    conn.execute("DROP TABLE IF EXISTS golden.case_versions")
    conn.execute("CREATE TABLE golden.case_versions AS SELECT * FROM safety.case_versions")   # the simulated safety desk adds versions/cases
    conn.execute("DROP TABLE IF EXISTS golden.vendor_file_dates")
    conn.execute("CREATE TABLE golden.vendor_file_dates AS SELECT id, file_date FROM lab_vendor.transfer")
    conn.execute("DROP TABLE IF EXISTS golden.lab_transfer")
    conn.execute("CREATE TABLE golden.lab_transfer AS SELECT * FROM lab_vendor.transfer")


def reset(conn: Connection, sim_seed: int | None = None) -> None:
    """Restore the seeded state at SIM_START_DAY: all EDC rows back to staging, runtime tables cleared."""
    has = conn.execute("SELECT to_regclass('golden.ae')").fetchone()[0]
    if not has:
        raise RuntimeError("no golden snapshot; run `make seed` first")
    conn.execute("TRUNCATE " + ", ".join(f"edc.{t}" for t in EDC_TABLES) + ", "
                 + ", ".join(f"edc_pending.{t}" for t in EDC_TABLES) + ", edc_pending.subject_updates CASCADE")
    for t in EDC_TABLES:
        conn.execute(f"INSERT INTO edc_pending.{t} SELECT * FROM golden.{t}")
    conn.execute("INSERT INTO edc_pending.subject_updates SELECT * FROM golden.subject_updates")
    conn.execute("UPDATE edc_pending.subject_updates SET applied = false")
    conn.execute("TRUNCATE safety.case_versions")
    conn.execute("INSERT INTO safety.case_versions SELECT * FROM golden.case_versions")      # ids preserved (failures cite v_cases#id)
    conn.execute("TRUNCATE lab_vendor.transfer")
    conn.execute("INSERT INTO lab_vendor.transfer SELECT * FROM golden.lab_transfer")                # ids preserved (failures cite transfer#id)
    conn.execute("UPDATE lab_vendor.transfer SET released = false")
    conn.execute("TRUNCATE " + ", ".join(RUNTIME_TABLES) + " RESTART IDENTITY")
    today = STUDY_START + timedelta(days=get_settings().sim_start_day)
    conn.execute("TRUNCATE ops.sim_clock")
    conn.execute("INSERT INTO ops.sim_clock (id, today, study_start) VALUES (1, %s, %s)", (today, STUDY_START))
    release_through(conn, today)   # back to the seeded state at SIM_START_DAY
    seed = sim_seed if sim_seed is not None else get_settings().seed
    conn.execute("INSERT INTO ops.sim_state (key, value) VALUES ('sim_seed', to_jsonb(%s::int))", (seed,))
