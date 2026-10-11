"""Prompt files in prompts/*.md. Each starts with `<!-- version: vN -->`; `{{name}}` placeholders are filled by render()."""
from __future__ import annotations

import re
from pathlib import Path

DIR = Path(__file__).parent / "prompts"
_VERSION = re.compile(r"<!--\s*version:\s*(\S+)\s*-->")


def load(job: str) -> tuple[str, str]:
    """Return (version, template) with the shared rules prepended."""
    text = (DIR / f"{job}.md").read_text()
    m = _VERSION.search(text)
    if not m:
        raise ValueError(f"prompt {job} has no version header")
    shared = (DIR / "_shared.md").read_text()
    return m.group(1), shared.strip() + "\n\n" + _VERSION.sub("", text).strip()


def render(job: str, **values: str) -> tuple[str, str]:
    version, template = load(job)
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{(\w+)\}\}", template)
    if left:
        raise ValueError(f"unfilled placeholders in {job}: {left}")
    return version, template
