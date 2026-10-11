"""LLM clients (spec §10): GeminiClient (live), ReplayClient (cache only), RecordingClient (cache, else live + write)."""
from __future__ import annotations

import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.llm import cache
from app.llm.embed import embed_texts

T = TypeVar("T", bound=BaseModel)
MAX_CONCURRENCY = 5
HTTP_TIMEOUT_MS = 60_000


@dataclass
class LLMResult:
    parsed: BaseModel | None          # None for a replay cache miss (is_stub) - callers must fall back
    is_stub: bool = False
    cache_hit: bool = False
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


def log_call(job: str, model: str, prompt_version: str, res: LLMResult, ok: bool, conn=None) -> None:
    """Every call is logged to ai.llm_calls (spec §10) on the caller's connection, so it shares the caller's transaction
    (a separate connection could block on locks the caller holds). Without a connection the call is not logged."""
    if conn is None:
        return
    try:
        with conn.transaction():   # savepoint: a logging failure must never poison the caller's transaction
            conn.execute("INSERT INTO ai.llm_calls (job, model, prompt_version, cache_hit, input_tokens, output_tokens, latency_ms, ok) "
                         "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (job, model, prompt_version, res.cache_hit, res.input_tokens,
                                                              res.output_tokens, res.latency_ms, ok))
    except Exception as exc:
        print(f"warning: could not log llm call: {exc}")


class LLMClient(ABC):
    @abstractmethod
    def structured(self, job: str, prompt: str, schema: type[T], *, model: str | None = None,
                   prompt_version: str = "v1", conn=None) -> LLMResult: ...

    def embed(self, texts: list[str]) -> list[list[float] | None]:
        return embed_texts(texts)


class GeminiClient(LLMClient):
    _sem = threading.Semaphore(MAX_CONCURRENCY)

    def __init__(self) -> None:
        from google import genai
        from google.genai import types
        self.s = get_settings()
        # bound every request: a hung call must fail over (callers fall back) instead of blocking the simulation
        self.client = genai.Client(api_key=self.s.gemini_api_key, http_options=types.HttpOptions(timeout=HTTP_TIMEOUT_MS))

    def _call(self, model: str, prompt: str, schema: type[T]):
        from google.genai import types
        cfg = types.GenerateContentConfig(temperature=0, response_mime_type="application/json", response_schema=schema)
        for attempt in range(6):
            try:
                with self._sem:
                    return self.client.models.generate_content(model=model, contents=prompt, config=cfg)
            except Exception as exc:
                text = str(exc)
                if "429" not in text and "503" not in text:
                    raise
                m = re.search(r"retry in ([\d.]+)s", text)
                time.sleep(min(60.0, float(m.group(1)) + 1 if m else 2 ** attempt * 2))
        raise RuntimeError("Gemini rate limit: retries exhausted")

    def structured(self, job, prompt, schema, *, model=None, prompt_version="v1", conn=None) -> LLMResult:
        model = model or self.s.gemini_fast_model
        t0 = time.time()
        tokens_in = tokens_out = 0
        parsed, error = None, None
        for attempt in range(2):   # one retry with the validation error appended (spec §10)
            p = prompt if error is None else f"{prompt}\n\nYour previous answer was invalid: {error}\nReturn corrected JSON only."
            resp = self._call(model, p, schema)
            tokens_in += resp.usage_metadata.prompt_token_count or 0
            tokens_out += resp.usage_metadata.candidates_token_count or 0
            try:
                parsed = schema.model_validate_json(resp.text)
                break
            except (ValidationError, ValueError) as exc:
                error = str(exc)[:500]
        res = LLMResult(parsed, model=model, input_tokens=tokens_in, output_tokens=tokens_out,
                        latency_ms=int((time.time() - t0) * 1000))
        log_call(job, model, prompt_version, res, ok=parsed is not None, conn=conn)
        if parsed is None:
            raise ValueError(f"{job}: model output failed validation twice: {error}")
        return res


class ReplayClient(LLMClient):
    """Serves cached responses only. A miss returns a clearly labeled stub (parsed=None, is_stub=True) and warns."""
    _warned: set[str] = set()

    def structured(self, job, prompt, schema, *, model=None, prompt_version="v1", conn=None) -> LLMResult:
        model = model or get_settings().gemini_fast_model
        hit = cache.get(job, cache.cache_key(job, model, prompt_version, prompt))
        if hit is None:
            if job not in self._warned:
                self._warned.add(job)
                print(f"warning: LLM replay cache miss for job '{job}' - returning stubs (record with make record-llm)")
            res = LLMResult(None, is_stub=True, model=model)
            log_call(job, model, prompt_version, res, ok=False, conn=conn)
            return res
        res = LLMResult(schema.model_validate(hit["response"]), cache_hit=True, model=model,
                        input_tokens=hit.get("input_tokens", 0), output_tokens=hit.get("output_tokens", 0))
        log_call(job, model, prompt_version, res, ok=True, conn=conn)
        return res


class RecordingClient(LLMClient):
    """Cache first; on a miss call Gemini and write the response to the cache."""

    def __init__(self) -> None:
        self.live = GeminiClient()

    def structured(self, job, prompt, schema, *, model=None, prompt_version="v1", conn=None) -> LLMResult:
        model = model or get_settings().gemini_fast_model
        key = cache.cache_key(job, model, prompt_version, prompt)
        hit = cache.get(job, key)
        if hit is not None:
            res = LLMResult(schema.model_validate(hit["response"]), cache_hit=True, model=model)
            log_call(job, model, prompt_version, res, ok=True, conn=conn)
            return res
        res = self.live.structured(job, prompt, schema, model=model, prompt_version=prompt_version, conn=conn)
        cache.put(job, key, {"job": job, "model": model, "prompt_version": prompt_version, "response": res.parsed.model_dump(),
                             "input_tokens": res.input_tokens, "output_tokens": res.output_tokens})
        return res


@lru_cache
def get_client() -> LLMClient:
    mode = get_settings().llm_mode
    if mode == "live":
        return GeminiClient()
    if mode == "record":
        return RecordingClient()
    return ReplayClient()
