import pytest

from app.config import get_settings
from app.seed.common import connect


@pytest.fixture(autouse=True)
def replay_mode(monkeypatch):
    """Tests never call Gemini: force replay mode (cache miss -> stub -> template fallback)."""
    monkeypatch.setenv("LLM_MODE", "replay")
    monkeypatch.setenv("LLM_QUERY_DRAFTS", "1")      # the drafter is tested with fake clients; ambient env must not switch it off
    get_settings.cache_clear()
    from app.llm.client import get_client
    get_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_client.cache_clear()


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
