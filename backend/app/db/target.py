"""Point the whole process at a different database (an eval fork). Evals run in their own process, so this never
affects the API server. Environment variables win over .env in pydantic-settings, so setting them is enough."""
from __future__ import annotations

import os

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.config import get_settings


def with_dbname(url: str, dbname: str) -> str:
    return make_conninfo(**{**conninfo_to_dict(url), "dbname": dbname})


def use_database(app_url: str, eval_url: str) -> None:
    os.environ["DATABASE_URL"] = app_url
    os.environ["EVAL_ADMIN_URL"] = eval_url
    get_settings.cache_clear()
    import app.db.connection as c
    if c._pool is not None:
        c._pool.close()
        c._pool = None
