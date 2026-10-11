from typing import Annotated

from fastapi import APIRouter, Depends

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
