"""JSON error shape `{code, message}` for every non-2xx response."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _body(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


async def _api_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(_body(exc.code, exc.message), status_code=exc.status)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(_body("invalid_request", "Yêu cầu không hợp lệ."), status_code=422)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code == 404:
        return JSONResponse(_body("not_found", "Không tìm thấy."), status_code=404)
    if exc.status_code == 405:
        return JSONResponse(_body("method_not_allowed", "Phương thức không được hỗ trợ."), status_code=405)
    return JSONResponse(_body("http_error", str(exc.detail)), status_code=exc.status_code)


INTERNAL_MESSAGE = "Lỗi máy chủ, vui lòng thử lại."


DEFAULT_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


def allowed_origins(app: Any) -> list[str]:
    """CORS origins from the settings held in `app.state.ircb`, or the default before startup."""
    st = getattr(app.state, "ircb", None)
    raw = st.settings.cors_origins if st is not None else DEFAULT_ORIGINS
    return [o.strip() for o in raw.split(",") if o.strip()]


async def _internal_error(request: Request, exc: Exception) -> JSONResponse:
    # The Exception handler runs in ServerErrorMiddleware, outside CORSMiddleware: add the header here.
    headers: dict[str, str] = {}
    origin = request.headers.get("origin")
    if origin is not None and origin in allowed_origins(request.app):
        headers = {"access-control-allow-origin": origin, "vary": "Origin"}
    return JSONResponse(_body("internal", INTERNAL_MESSAGE), status_code=500, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Exception, _internal_error)
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
