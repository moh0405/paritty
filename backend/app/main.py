from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import system

app = FastAPI(title="LockStep")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(system.router, prefix="/api")
