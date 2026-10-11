"""`make reset`: restore the seeded state at SIM_START_DAY (needs the golden snapshot from `make seed`)."""
from app.seed.common import connect
from app.sim.reset import reset


def main() -> None:
    with connect() as conn:
        reset(conn)
        conn.commit()
        print("reset to", conn.execute("SELECT today FROM ops.sim_clock").fetchone()[0])


if __name__ == "__main__":
    main()
