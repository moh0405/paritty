"""Scenario YAML (spec §12)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DIR = Path(__file__).resolve().parents[2] / "scenarios"


@dataclass
class Injection:
    kind: str
    count: int = 1
    params: dict = field(default_factory=dict)


@dataclass
class Scenario:
    name: str
    advance_days: int
    model: str
    prompt_version: str
    injections: list[Injection]
    baseline: bool = True
    agent: bool = False          # compare the same period with and without the data-manager agent


def _expand(text: str) -> str:
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), _default(m.group(1))), text)


def _default(name: str) -> str:
    from app.config import get_settings
    return {"GEMINI_FAST_MODEL": get_settings().gemini_fast_model, "GEMINI_STRONG_MODEL": get_settings().gemini_strong_model}.get(name, "")


def load(name: str) -> Scenario:
    raw = yaml.safe_load(_expand((DIR / f"{name}.yaml").read_text()))
    return Scenario(raw["name"], int(raw["advance_days"]), raw.get("model", ""), raw.get("prompt_version", "v1"),
                    [Injection(i["kind"], int(i.get("count", 1)), i.get("params") or {}) for i in raw.get("injections", [])], raw.get("baseline", True), raw.get("agent", False))


def list_scenarios() -> list[dict]:
    return [{"name": p.stem, "advance_days": s.advance_days, "injections": [{"kind": i.kind, "count": i.count} for i in s.injections]}
            for p in sorted(DIR.glob("*.yaml")) for s in [load(p.stem)]]
