"""Chunk a markdown protocol by heading into ~150-300 word chunks (spec §7.5)."""
from __future__ import annotations

import re
from dataclasses import dataclass

MIN_WORDS, MAX_WORDS = 90, 300


@dataclass(frozen=True)
class Chunk:
    section: str
    text: str
    is_synthetic: bool


def _split_sections(md: str) -> list[tuple[str, str]]:
    parts = re.split(r"^## +(.+)$", md, flags=re.M)
    return [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts), 2)]


def _split_long(heading: str, body: str) -> list[tuple[str, str]]:
    paras = [p for p in body.split("\n\n") if p.strip()]
    out, cur = [], []
    for p in paras:
        if cur and sum(len(x.split()) for x in cur) + len(p.split()) > MAX_WORDS:
            out.append((heading, "\n\n".join(cur)))
            cur = []
        cur.append(p)
    if cur:
        out.append((heading, "\n\n".join(cur)))
    return out


def chunk_protocol(md: str) -> list[Chunk]:
    units: list[tuple[str, str]] = []
    for heading, body in _split_sections(md):
        units.extend(_split_long(heading, body) if len(body.split()) > MAX_WORDS else [(heading, body)])
    chunks: list[Chunk] = []
    heads: list[str] = []
    bodies: list[str] = []

    def flush() -> None:
        if bodies:
            text = "\n\n".join(f"{h}\n{b}" for h, b in zip(heads, bodies))
            chunks.append(Chunk(" / ".join(dict.fromkeys(heads)), text, any("[SYNTHETIC]" in h for h in heads)))
        heads.clear()
        bodies.clear()

    for heading, body in units:
        words = sum(len(b.split()) for b in bodies)
        if bodies and (words >= MIN_WORDS or words + len(body.split()) > MAX_WORDS):
            flush()
        heads.append(heading)
        bodies.append(body)
    flush()
    return chunks
