"""Application settings (environment variables, see spec section 7)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PDF = "./data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_model: str
    llm_model_small: str = ""
    judge_model: str | None = None
    vlm_model: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    ollama_api_base: str = "http://localhost:11434"  # LLM only: local Ollama or https://ollama.com
    ollama_api_key: str | None = (
        None  # only for https://ollama.com directly; a signed-in local Ollama needs none
    )
    embed_api_base: str = "http://localhost:11434"  # Ollama serving EMBED_MODEL (ollama.com has none)
    llm_timeout_s: int = 60  # per call; hosted open models answer slower than OpenAI

    embed_model: str = "ollama/qwen3-embedding:4b"  # what the shipped index/ was embedded with
    embed_dimensions: int = 1024
    embed_cache_dir: Path = Path("./var/embed_cache")
    llm_seed: int = 42
    index_dir: Path = Path("./index")
    top_k: int = 8
    refusal_threshold: float = 0.35
    trace_dir: Path = Path("./traces")
    llm_price_in: float | None = None
    llm_price_out: float | None = None

    app_env: str = "dev"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    database_url: str = "sqlite:///./var/app.db"
    qdrant_url: str | None = None
    qdrant_path: str = "./var/qdrant"
    qdrant_api_key: str | None = None
    qdrant_collection_prefix: str = "ircb_"
    auto_load_index: bool = True
    page_cache_dir: Path = Path("./var/page_cache")
    pdf_path: Path = Field(default=Path(DEFAULT_PDF))

    def model_post_init(self, __context: object) -> None:
        if not self.llm_model_small:
            self.llm_model_small = self.llm_model

    def ensure_dirs(self) -> None:
        """Create the runtime directories (gitignored, absent on a fresh checkout)."""
        dirs = [self.trace_dir, self.embed_cache_dir, self.page_cache_dir]
        if self.qdrant_mode == "embedded":
            dirs.append(Path(self.qdrant_path))
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)

    @property
    def qdrant_mode(self) -> Literal["server", "embedded"]:
        return "server" if self.qdrant_url else "embedded"


@lru_cache
def get_settings() -> Settings:
    return Settings()
