"""FastAPI app factory. Routers are registered in `_routers`; `app` is the uvicorn entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ircb.settings import Settings
from starlette.types import ASGIApp, Receive, Scope, Send

from ircb_api.errors import allowed_origins, install_error_handlers
from ircb_api.routers import chat, facts, health, pages, sessions, traces
from ircb_api.schemas import ErrorOut, StatusOut
from ircb_api.state import AppState, build_state

_routers = [health.router, chat.router, sessions.router, pages.router, facts.router, traces.router]


class _LazyCORS:
    """CORS whose origins come from the settings held in `app.state.ircb` once the app is serving.

    Nothing reads settings at import or in `create_app()`, so the OpenAPI schema can be dumped
    without environment variables. Before startup (no state) the default origin applies.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._inner: ASGIApp | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if self._inner is None:
            self._inner = CORSMiddleware(
                self.app,
                allow_origins=allowed_origins(scope["app"]),
                allow_methods=["*"],
                allow_headers=["*"],
            )
        await self._inner(scope, receive, send)


def _extra_schemas(app: FastAPI) -> None:
    """Add the SSE payload and error DTOs to components.schemas (no route returns them as JSON)."""
    original = app.openapi

    def openapi() -> dict[str, Any]:
        first = app.openapi_schema is None
        spec = original()
        if first:
            schemas = spec.setdefault("components", {}).setdefault("schemas", {})
            for model in (StatusOut, ErrorOut):
                js = model.model_json_schema(ref_template="#/components/schemas/{model}")
                for name, sub in js.pop("$defs", {}).items():
                    schemas.setdefault(name, sub)
                schemas[model.__name__] = js
        return spec

    app.openapi = openapi  # type: ignore[method-assign]


def create_app(state: AppState | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.ircb = state if state is not None else build_state(Settings())
        yield

    app = FastAPI(title="ircb API", lifespan=lifespan)
    app.add_middleware(_LazyCORS)
    install_error_handlers(app)
    _extra_schemas(app)
    for r in _routers:
        app.include_router(r, prefix="/v1")
    return app


app = create_app()
