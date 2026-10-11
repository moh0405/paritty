"""Database forks for evals (spec §12). TemplateDbForkManager copies a quiet golden database with CREATE DATABASE ... TEMPLATE;
TigerForkManager forks a Tiger Cloud service through the Tiger CLI (see docs/TIGER.md)."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.config import get_settings
from app.db.target import with_dbname
from app.sim.reset import reset

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
    """Forks the golden Tiger Cloud service with `tiger service fork` and removes it with `tiger service delete`
    (CLI 0.26, see docs/TIGER.md). A fork is a whole new service, so its URLs differ from the golden's by host and port.
    Roles are copied with their passwords, which is why EVAL_ADMIN_URL's credentials work on the fork."""

    FORK_TIMEOUT = "30m"

    def __init__(self) -> None:
        if shutil.which("tiger") is None:
            raise RuntimeError("tiger CLI not found; install it or set FORK_BACKEND=template")
        self.s = get_settings()
        if not self.s.golden_service_id:
            raise RuntimeError("GOLDEN_SERVICE_ID is not set; it names the Tiger service that eval forks are taken from")

    def _tiger(self, *args: str) -> str:
        done = subprocess.run(["tiger", *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"tiger {' '.join(args[:2])} failed: {done.stderr.strip() or done.stdout.strip()}")
        return done.stdout

    def create(self, name: str) -> Fork:
        t = time.time()
        try:
            # --no-set-default: a fork must not become the CLI's default service; --with-password: the fork gets its own tsdbadmin password
            info = json.loads(self._tiger("service", "fork", self.s.golden_service_id, "--name", name, "--no-set-default",
                                          "--with-password", "--wait-timeout", self.FORK_TIMEOUT, "--output", "json"))
            seconds = time.time() - t
            where = {"host": info["host"], "port": str(info["port"]), "dbname": info["database"]}
            app_url = make_conninfo(user=info["role"], password=info["password"], sslmode="require", **where)
            eval_url = make_conninfo(**{**conninfo_to_dict(self.s.eval_admin_url), **where})
            with psycopg.connect(app_url) as c:   # the golden service is also the live demo database: start every fork from the seeded state
                reset(c)
        except Exception:
            self._delete(name)   # the service may exist even though the command failed (timeout, unreadable output)
            raise
        return Fork(info["service_id"], app_url, eval_url, seconds)

    def _delete(self, name_or_id: str) -> None:
        subprocess.run(["tiger", "service", "delete", name_or_id, "--confirm"], capture_output=True, text=True)

    def delete(self, fork: Fork) -> None:
        self._tiger("service", "delete", fork.name, "--confirm")


def get_fork_manager() -> ForkManager:
    return TigerForkManager() if get_settings().fork_backend == "tiger" else TemplateDbForkManager()
