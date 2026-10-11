"""Minimal in-process job manager: long jobs return 202 {job_id}; progress via SSE (spec §13)."""
from __future__ import annotations

import threading
import uuid
from typing import Callable

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_running: set[str] = set()


def start(kind: str, total: int, fn: Callable[[Callable[[int, dict], None]], dict], exclusive: str | None = None) -> str:
    """Run fn(progress_cb) in a thread. `exclusive` names a resource that only one job may hold at a time."""
    with _lock:
        if exclusive and exclusive in _running:
            raise RuntimeError(f"{exclusive} is busy")
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {"id": job_id, "kind": kind, "status": "running", "done": 0, "total": total, "last": None, "result": None, "error": None}
        if exclusive:
            _running.add(exclusive)

    def progress(done: int, last: dict) -> None:
        _jobs[job_id].update(done=done, last=last)

    def work() -> None:
        try:
            _jobs[job_id]["result"] = fn(progress)
            _jobs[job_id]["status"] = "done"
        except Exception as exc:  # surfaced to the client
            _jobs[job_id].update(status="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            with _lock:
                _running.discard(exclusive or "")

    threading.Thread(target=work, daemon=True).start()
    return job_id


def get(job_id: str) -> dict | None:
    return _jobs.get(job_id)
