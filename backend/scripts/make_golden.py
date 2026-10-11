"""Reset the simulation to the seeded state and make it the source of eval forks (`make golden`, last step of `make seed`).
Local Docker: snapshot it as the template database; other sessions on the main database are terminated while it is copied.
Tiger Cloud: the service itself (GOLDEN_SERVICE_ID) is the fork source, so there is nothing to copy."""
from app.config import get_settings
from app.evals.fork_manager import TemplateDbForkManager
from app.seed.common import connect
from app.sim.reset import reset


def main() -> None:
    with connect() as conn:
        reset(conn)
        conn.commit()
    s = get_settings()
    if s.fork_backend == "tiger":
        print(f"seeded state restored; eval forks are taken from Tiger service {s.golden_service_id}")
        return
    secs = TemplateDbForkManager().snapshot_golden("tsdb")
    print(f"golden template database ready ({secs:.1f}s)")


if __name__ == "__main__":
    main()
