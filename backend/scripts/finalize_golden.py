"""Set the sim clock and release staged data up to SIM_START_DAY (spec §7.1, §9.1 step 1)."""
from datetime import timedelta

from app.config import get_settings
from app.seed.common import connect
from app.sim.constants import STUDY_START
from app.sim import reset
from app.sim.ingestor import release_through


def main() -> None:
    today = STUDY_START + timedelta(days=get_settings().sim_start_day)
    with connect() as conn:
        conn.execute("TRUNCATE ops.sim_clock")
        conn.execute("INSERT INTO ops.sim_clock (id, today, study_start) VALUES (1, %s, %s)", (today, STUDY_START))
        moved, _ = release_through(conn, today)
        n = conn.execute("UPDATE lab_vendor.transfer SET released = (file_date <= %s)", (today,)).rowcount
        reset.snapshot(conn)
        conn.commit()
    print(f"sim clock: {today} (study day {get_settings().sim_start_day}); released: {moved}; vendor rows flagged: {n}")
    with connect() as conn:
        conn.autocommit = True
        for agg in ("edc.site_vitals_weekly",):
            conn.execute(f"CALL refresh_continuous_aggregate('{agg}', NULL, NULL)")


if __name__ == "__main__":
    main()
