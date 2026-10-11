"""Reset the simulation to the seeded state and snapshot it as the eval template database (`make golden`, last step of `make seed`).
Other sessions on the main database are terminated while the template is copied."""
from app.evals.fork_manager import TemplateDbForkManager
from app.seed.common import connect
from app.sim.reset import reset


def main() -> None:
    with connect() as conn:
        reset(conn)
        conn.commit()
    secs = TemplateDbForkManager().snapshot_golden("tsdb")
    print(f"golden template database ready ({secs:.1f}s)")


if __name__ == "__main__":
    main()
