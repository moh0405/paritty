import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import checks, evals, findings, medical, queries, recon, search, sim, sites, system

app = FastAPI(title="LockStep")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (system.router, sim.router, checks.router, queries.router, findings.router, search.router, recon.router, medical.router, sites.router, evals.router):
    app.include_router(r, prefix="/api")


@app.exception_handler(psycopg.errors.InsufficientPrivilege)
async def forbidden(_: Request, exc: psycopg.errors.InsufficientPrivilege) -> JSONResponse:
    # e.g. study_lead reading patient-level tables: "Your role can't see ..." (spec §9.9)
    return JSONResponse(status_code=403, content={"detail": "Your role can't see this data."})
