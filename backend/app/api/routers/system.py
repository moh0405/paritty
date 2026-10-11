import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from app import jobs
from app.db.connection import get_pool
from app.deps import Caller, get_caller

router = APIRouter()


@router.get("/health")
def health() -> dict:
    try:
        with get_pool().connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "db": True}
    except Exception as exc:  # health must not raise
        return {"status": "degraded", "db": False, "error": str(exc)[:200]}


@router.get("/me")
def me(caller: Annotated[Caller, Depends(get_caller)]) -> dict:
    return {"role": caller.role, "site_scope": caller.site_scope, "user": caller.user}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str):
    if jobs.get(job_id) is None:
        raise HTTPException(404, "unknown job")

    async def stream():
        last = None
        while True:
            job = jobs.get(job_id)
            snap = json.dumps({k: job[k] for k in ("status", "done", "total", "last", "error")})
            if snap != last:
                yield {"event": "progress", "data": snap}
                last = snap
            if job["status"] != "running":
                return
            await asyncio.sleep(0.25)
    return EventSourceResponse(stream())
