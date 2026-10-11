"""Database forks for evals (spec §12). TemplateDbForkManager copies a quiet golden database with CREATE DATABASE ... TEMPLATE;
TigerForkManager wraps the Tiger CLI (flags unverified - see docs/DECISIONS.md)."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import psycopg
from psycopg import sql

from app.config import get_settings
from app.db.target import with_dbname

GOLDEN_DB = "lockstep_golden"


@dataclass
class Fork:
    name: str
    app_url: str
    eval_url: str
    seconds: float


class ForkManager(ABC):
    @abstractmethod
    def create(self, name: str) -> Fork: ...

    @abstractmethod
    def delete(self, fork: Fork) -> None: ...


class TemplateDbForkManager(ForkManager):
    def __init__(self, golden: str = GOLDEN_DB):
        self.golden = golden
        self.s = get_settings()

    def _admin(self) -> psycopg.Connection:
        return psycopg.connect(with_dbname(self.s.database_url, "postgres"), autocommit=True)

    def create(self, name: str) -> Fork:
        t = time.time()
        with self._admin() as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
            c.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(name), sql.Identifier(self.golden)))
        return Fork(name, with_dbname(self.s.database_url, name), with_dbname(self.s.eval_admin_url, name), time.time() - t)

    def delete(self, fork: Fork) -> None:
        with self._admin() as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(fork.name)))

    def snapshot_golden(self, source: str = "tsdb") -> float:
        """(Re)create the golden template from the live database. Other sessions on `source` are terminated: a template must be idle."""
        t = time.time()
        with self._admin() as c:
            c.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (source,))
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(self.golden)))
            c.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(self.golden), sql.Identifier(source)))
        return time.time() - t


class TigerForkManager(ForkManager):
    """Wraps `tiger service fork` / `tiger service delete`. The exact flags and JSON output were NOT verified (the CLI is not
    installed in development); confirm with `tiger service fork --help` before use."""

    def __init__(self) -> None:
        if shutil.which("tiger") is None:
            raise RuntimeError("tiger CLI not found; install it or set FORK_BACKEND=template")
        self.s = get_settings()

    def create(self, name: str) -> Fork:
        t = time.time()
        out = subprocess.run(["tiger", "service", "fork", self.s.golden_service_id, "--name", name, "--output", "json"],
                             capture_output=True, text=True, check=True).stdout
        info = json.loads(out)
        url = info.get("connection_string") or info["url"]
        return Fork(info.get("service_id", name), url, url, time.time() - t)

    def delete(self, fork: Fork) -> None:
        subprocess.run(["tiger", "service", "delete", fork.name, "--confirm"], check=True, capture_output=True)


def get_fork_manager() -> ForkManager:
    return TigerForkManager() if get_settings().fork_backend == "tiger" else TemplateDbForkManager()
