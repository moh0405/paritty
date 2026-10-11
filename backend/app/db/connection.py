from contextlib import contextmanager
from typing import Iterator

from psycopg import Connection, sql
from psycopg_pool import ConnectionPool

from app.config import get_settings
from app.domain.enums import Role

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(get_settings().database_url, min_size=1, max_size=10, open=True)
    return _pool


@contextmanager
def scoped_connection(role: Role, site_scope: str | None = None) -> Iterator[Connection]:
    """One transaction per request: SET LOCAL ROLE + app.site_scope (spec §13)."""
    with get_pool().connection() as conn:
        with conn.transaction():
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role.value)))
            conn.execute("SELECT set_config('app.site_scope', %s, true)", (site_scope,))
            yield conn


@contextmanager
def as_role(conn: Connection, role: Role, site_scope: str | None = None) -> Iterator[Connection]:
    """Run reads on an existing connection as `role` (RLS + grants apply). A rolled-back savepoint undoes SET LOCAL,
    so the caller's session is unchanged and it still sees the caller's uncommitted rows."""
    with conn.transaction(force_rollback=True):
        conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role.value)))
        conn.execute("SELECT set_config('app.site_scope', %s, true)", (site_scope,))
        yield conn
