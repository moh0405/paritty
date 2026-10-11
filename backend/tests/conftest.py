import pytest

from app.seed.common import connect


@pytest.fixture
def db():
    """A connection whose work is always rolled back. Skips if the database isn't reachable or seeded."""
    try:
        conn = connect()
        seeded = conn.execute("SELECT count(*) FROM ops.sim_clock").fetchone()[0]
    except Exception:
        pytest.skip("database not reachable")
    if not seeded:
        pytest.skip("database not seeded (run make seed)")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
