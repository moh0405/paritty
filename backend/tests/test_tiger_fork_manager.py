"""TigerForkManager against a fake `tiger` CLI: no network, no Tiger account needed."""
import json
import subprocess
from contextlib import contextmanager

import pytest
from psycopg.conninfo import conninfo_to_dict

from app.config import get_settings
from app.evals import fork_manager as fm_module
from app.evals.fork_manager import TigerForkManager

FORK_JSON = {"service_id": "forkid0001", "name": "fork_abc", "role": "tsdbadmin", "password": "fork-secret",
             "host": "forkid0001.proj.tsdb.cloud.timescale.com", "port": 31000, "database": "tsdb", "status": "READY"}


class FakeTiger:
    def __init__(self, fork_stdout: str = json.dumps(FORK_JSON), fork_code: int = 0):
        self.calls: list[list[str]] = []
        self.fork_stdout, self.fork_code = fork_stdout, fork_code

    def __call__(self, cmd, **_):
        self.calls.append(cmd)
        if cmd[1:3] == ["service", "fork"]:
            return subprocess.CompletedProcess(cmd, self.fork_code, self.fork_stdout, "quota exceeded" if self.fork_code else "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def deleted(self) -> list[str]:
        return [c[3] for c in self.calls if c[1:3] == ["service", "delete"]]


@pytest.fixture
def tiger(monkeypatch):
    monkeypatch.setenv("FORK_BACKEND", "tiger")
    monkeypatch.setenv("GOLDEN_SERVICE_ID", "goldenid01")
    monkeypatch.setenv("EVAL_ADMIN_URL", "postgresql://eval_admin:eval-secret@golden.host:5432/tsdb?sslmode=require")
    get_settings.cache_clear()
    fake = FakeTiger()
    monkeypatch.setattr(fm_module.shutil, "which", lambda _: "/usr/local/bin/tiger")
    monkeypatch.setattr(fm_module.subprocess, "run", fake)
    resets: list[str] = []

    @contextmanager
    def connect(url, **_):
        yield url

    monkeypatch.setattr(fm_module.psycopg, "connect", connect)
    monkeypatch.setattr(fm_module, "reset", resets.append)
    fake.resets = resets
    return fake


def test_fork_command_keeps_the_default_service_and_asks_for_the_password(tiger):
    TigerForkManager().create("fork_abc")
    cmd = tiger.calls[0]
    assert cmd[:4] == ["tiger", "service", "fork", "goldenid01"]
    assert cmd[cmd.index("--name") + 1] == "fork_abc"
    assert {"--no-set-default", "--with-password"} <= set(cmd)
    assert cmd[cmd.index("--output") + 1] == "json"


def test_fork_urls_point_at_the_new_service_with_the_right_credentials(tiger):
    f = TigerForkManager().create("fork_abc")
    app, ev = conninfo_to_dict(f.app_url), conninfo_to_dict(f.eval_url)
    assert f.name == "forkid0001"
    assert (app["host"], app["port"], app["user"], app["password"]) == (FORK_JSON["host"], "31000", "tsdbadmin", "fork-secret")
    assert (ev["host"], ev["port"], ev["user"], ev["password"]) == (FORK_JSON["host"], "31000", "eval_admin", "eval-secret")
    assert app["sslmode"] == ev["sslmode"] == "require"
    assert tiger.resets == [f.app_url]      # every fork starts from the seeded state
    assert tiger.deleted() == []


def test_delete_is_by_service_id_and_skips_the_prompt(tiger):
    m = TigerForkManager()
    m.delete(m.create("fork_abc"))
    assert tiger.calls[-1] == ["tiger", "service", "delete", "forkid0001", "--confirm"]


def test_failed_fork_command_raises_and_cleans_up_by_name(tiger):
    tiger.fork_code = 1
    with pytest.raises(RuntimeError, match="quota exceeded"):
        TigerForkManager().create("fork_abc")
    assert tiger.deleted() == ["fork_abc"]


def test_unreadable_fork_output_cleans_up_by_name(tiger):
    tiger.fork_stdout = "not json"
    with pytest.raises(ValueError):
        TigerForkManager().create("fork_abc")
    assert tiger.deleted() == ["fork_abc"]


def test_failure_after_the_fork_exists_still_deletes_it(tiger, monkeypatch):
    def boom(_):
        raise RuntimeError("no golden snapshot")

    monkeypatch.setattr(fm_module, "reset", boom)
    with pytest.raises(RuntimeError, match="no golden snapshot"):
        TigerForkManager().create("fork_abc")
    assert tiger.deleted() == ["fork_abc"]


def test_missing_cli_or_golden_service_is_reported(tiger, monkeypatch):
    monkeypatch.setenv("GOLDEN_SERVICE_ID", "")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="GOLDEN_SERVICE_ID"):
        TigerForkManager()
    monkeypatch.setattr(fm_module.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="tiger CLI not found"):
        TigerForkManager()
