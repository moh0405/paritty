"""On-disk cache of Gemini responses, committed to the repo so LLM_MODE=replay runs without a key (spec §5, §10)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "llm_cache"


def cache_key(job: str, model: str, prompt_version: str, prompt: str) -> str:
    return hashlib.sha256(f"{job}|{model}|{prompt_version}|{prompt}".encode()).hexdigest()


def get(job: str, key: str) -> dict | None:
    f = ROOT / job / f"{key}.json"
    return json.loads(f.read_text()) if f.exists() else None


def put(job: str, key: str, payload: dict) -> None:
    d = ROOT / job
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.json").write_text(json.dumps(payload, indent=1, sort_keys=True))
