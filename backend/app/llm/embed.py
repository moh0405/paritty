"""Embedding helper with an on-disk cache (spec §10). Returns None for texts it cannot embed:
no cached vector and no usable API key/mode. Callers then leave the vector NULL and search falls back to BM25."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from app.config import get_settings

CACHE = Path(__file__).resolve().parents[2] / "fixtures" / "llm_cache" / "embeddings"


def _key(text: str) -> str:
    s = get_settings()
    return hashlib.sha256(f"{s.gemini_embed_model}|{s.embed_dim}|{text}".encode()).hexdigest()


def to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def embed_texts(texts: list[str]) -> list[list[float] | None]:
    s = get_settings()
    out: list[list[float] | None] = [None] * len(texts)
    missing: list[int] = []
    for i, t in enumerate(texts):
        f = CACHE / f"{_key(t)}.json"
        if f.exists():
            out[i] = json.loads(f.read_text())
        else:
            missing.append(i)
    if not missing or s.llm_mode == "replay" or not s.gemini_api_key:
        if missing:
            print(f"embed: {len(missing)}/{len(texts)} texts have no cached vector (mode={s.llm_mode}, key={'set' if s.gemini_api_key else 'unset'})")
        return out
    from concurrent.futures import ThreadPoolExecutor

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=s.gemini_api_key)
    cfg = types.EmbedContentConfig(output_dimensionality=s.embed_dim)

    def one(i: int) -> tuple[int, list[float]]:
        # gemini-embedding-2 folds a list of contents into ONE embedding, so embed one text per call
        for attempt in range(8):
            try:
                res = client.models.embed_content(model=s.gemini_embed_model, contents=texts[i], config=cfg)
                return i, list(res.embeddings[0].values)
            except Exception:
                if attempt == 7:
                    raise
                time.sleep(20 if attempt else 5)   # free tier: 100 requests/min; the 429 asks for ~40 s

    with ThreadPoolExecutor(max_workers=5) as pool:
        for i, vec in pool.map(one, missing):
            out[i] = vec
            if s.llm_mode == "record":
                CACHE.mkdir(parents=True, exist_ok=True)
                (CACHE / f"{_key(texts[i])}.json").write_text(json.dumps(vec))
    return out
