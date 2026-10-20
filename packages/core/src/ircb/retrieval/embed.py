"""Embedding backend (LiteLLM) and on-disk cached embedder."""

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Protocol

from ircb.llm.retry import retryable as _retryable
from ircb.settings import Settings

BATCH = 100  # Gemini's batchEmbedContents takes at most 100 texts; OpenAI takes far more
RETRIES = 5  # with doubling waits (2 s … 32 s): enough to ride out a per-minute rate limit


class EmbedBackend(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LiteLLMEmbedBackend:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _kwargs(self, batch: list[str]) -> dict[str, Any]:
        s = self.settings
        kwargs: dict[str, Any] = {"model": s.embed_model, "input": batch, "dimensions": s.embed_dimensions}
        if s.embed_model.startswith("ollama/"):
            # the Ollama that embedded the index embeds every question too (local, or on the server)
            kwargs["api_base"] = s.ollama_api_base
            if s.ollama_api_key:
                kwargs["api_key"] = s.ollama_api_key
        return kwargs

    def _call(self, batch: list[str]) -> list[list[float]]:
        import litellm

        for attempt in range(RETRIES + 1):
            try:
                resp: Any = litellm.embedding(**self._kwargs(batch))
                return [list(map(float, d["embedding"])) for d in resp["data"]]
            except Exception as exc:
                if attempt == RETRIES or not _retryable(exc):
                    raise
                time.sleep(2 ** (attempt + 1))
        raise RuntimeError("unreachable")

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            out.extend(self._call(texts[i : i + BATCH]))
        return out


class Embedder:
    def __init__(self, backend: EmbedBackend, cache_dir: Path, model: str, dimensions: int) -> None:
        self.backend = backend
        self.cache_dir = Path(cache_dir)
        self.model = model
        self.dimensions = dimensions

    def _path(self, text: str) -> Path:
        key = hashlib.sha256(f"{self.model}|{self.dimensions}|{text}".encode()).hexdigest()
        return self.cache_dir / key[:2] / f"{key}.json"

    def embed(self, texts: list[str]) -> list[list[float]]:
        found: dict[str, list[float]] = {}
        missing: list[str] = []
        for t in dict.fromkeys(texts):
            p = self._path(t)
            if p.exists():
                found[t] = json.loads(p.read_text(encoding="utf-8"))
            else:
                missing.append(t)
        # one batch at a time, cached as it lands: a run stopped by a rate limit resumes where it was
        for i in range(0, len(missing), BATCH):
            batch = missing[i : i + BATCH]
            for t, v in zip(batch, self.backend.embed(batch), strict=True):
                p = self._path(t)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(v), encoding="utf-8")
                found[t] = v
        return [found[t] for t in texts]
