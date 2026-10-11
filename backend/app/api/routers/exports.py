from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.audit.logger import audit
from app.db.connection import get_pool, scoped_connection
from app.deps import Caller, get_caller
from app.domain.enums import Role
from app.exports import csv as csv_export
from app.exports.signal_pack import build_pack
from app.sim.clock import TrialClock

router = APIRouter(prefix="/export", tags=["export"])


def _audit(caller: Caller, what: str) -> None:
    with get_pool().connection() as c:
        audit(c, TrialClock(c).today(), caller.user, "export", "export", what, {}, role=caller.role.value)


@router.get("/signal-pack.pdf")
def signal_pack(caller: Annotated[Caller, Depends(get_caller)]) -> Response:
    if caller.role not in (Role.MEDICAL_MONITOR, Role.DATA_MANAGER):
        raise HTTPException(403, "Only a medical monitor or data manager can export the signal review pack")
    with get_pool().connection() as sysconn:
        today = TrialClock(sysconn).today()
    with scoped_connection(caller.role, caller.site_scope) as conn:
        pdf = build_pack(conn, today)
    _audit(caller, "signal-pack.pdf")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="signal-pack-{today}.pdf"'})


@router.get("/{name}.csv")
def export_csv(name: str, caller: Annotated[Caller, Depends(get_caller)]) -> Response:
    if name not in csv_export.SQL:
        raise HTTPException(404, "export one of: " + ", ".join(csv_export.SQL))
    with scoped_connection(caller.role, caller.site_scope) as conn:
        body = csv_export.export(conn, name, caller.site_scope)
    _audit(caller, f"{name}.csv")
    return Response(body, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}-{datetime.now():%Y%m%d}.csv"'})
