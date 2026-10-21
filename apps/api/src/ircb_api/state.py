"""Application state: the objects routes share, built once at startup."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from fastapi import Request
from ircb.domain.models import Answer, Chunk, TurnState
from ircb.pages import PageRenderer
from ircb.service import AnswerService
from ircb.settings import Settings
from ircb.storage import artefacts
from ircb.storage.db import make_engine, upgrade_db
from ircb.storage.fact_repo import SqlFactStore
from ircb.storage.loader import ManifestMismatchError
from ircb.storage.session_repo import SessionRepo

from ircb_api.auth import ClerkAuth


class ServiceLike(Protocol):
    def ask(
        self,
        message: str,
        prev_state: TurnState | None = None,
        history: list[tuple[str, str]] | None = None,
        on_step: Callable[[str], None] | None = None,
    ) -> Answer: ...


@dataclass
class AppState:
    settings: Settings
    service: ServiceLike
    sessions: SessionRepo
    facts: SqlFactStore
    chunks: dict[str, Chunk]
    renderer: PageRenderer
    manifest: artefacts.Manifest
    lock: threading.Lock
    auth: ClerkAuth | None = None  # None: no sign-in, sessions are per browser (X-Client-Id)


def get_state(request: Request) -> AppState:
    """FastAPI dependency: the AppState the lifespan stored on the app."""
    return cast(AppState, request.app.state.ircb)


def build_state(settings: Settings) -> AppState:
    """Open every store; known start-up failures become a one-line RuntimeError."""
    # LiteLLM is imported here, before serving: imported first inside a request's worker thread it
    # deadlocks with its own logging filter importing a submodule on the event loop (docker run)
    import litellm  # noqa: F401

    index_dir = settings.index_dir
    if not (index_dir / artefacts.MANIFEST).is_file():
        raise RuntimeError(
            f"No index at {index_dir} ({artefacts.MANIFEST} missing): build it with "
            f"`ircb ingest <pdf> --out {index_dir}` (see README)."
        )
    try:
        service = AnswerService.from_settings(settings)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Index at {index_dir} is incomplete ({exc.filename} missing): rebuild it with "
            f"`ircb ingest <pdf> --out {index_dir}`."
        ) from exc
    except ManifestMismatchError as exc:
        raise RuntimeError(str(exc)) from exc
    engine = make_engine(settings.database_url)
    upgrade_db(engine)
    chunks = {c.chunk_id: c for c in map(Chunk.model_validate, artefacts.read_chunks(index_dir))}
    page_map = artefacts.read_page_map(index_dir)
    return AppState(
        settings=settings,
        service=service,
        sessions=SessionRepo(engine),
        facts=SqlFactStore(engine),
        chunks=chunks,
        renderer=PageRenderer(settings.pdf_path, page_map, settings.page_cache_dir),
        manifest=artefacts.read_manifest(index_dir),
        lock=threading.Lock(),
        auth=_auth(settings),
    )


def _auth(settings: Settings) -> ClerkAuth | None:
    if not settings.clerk_publishable_key:
        return None
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    try:
        return ClerkAuth(settings.clerk_publishable_key, origins)
    except ValueError as exc:
        raise RuntimeError(f"CLERK_PUBLISHABLE_KEY: {exc}") from exc
