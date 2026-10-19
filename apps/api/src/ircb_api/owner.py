"""Who owns a conversation: the request's owner id, matched exactly against the session's owner.

With Clerk configured (``AppState.auth``) every chat / history request needs a valid session token
in ``Authorization: Bearer``; the owner is ``user:<clerk user id>`` and ``X-Client-Id`` is ignored.

Without it the web sends a random per-browser id in ``X-Client-Id``; that separates one browser's
history from another's but is not authentication (anyone holding the id can read those sessions).
A request without the header shares one public bucket. The prefixes keep the namespaces apart.
"""

from __future__ import annotations

import logging
import re
from typing import Annotated

from fastapi import Depends, Header

from ircb_api.auth import AuthError, AuthUnavailable
from ircb_api.errors import ApiError
from ircb_api.state import AppState, get_state

log = logging.getLogger(__name__)

CLIENT_HEADER = "X-Client-Id"
PUBLIC_OWNER = "public"
_CLIENT_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_BEARER_RE = re.compile(r"^Bearer\s+(\S+)$", re.IGNORECASE)


def _signed_in(st: AppState, authorization: str | None) -> str:
    assert st.auth is not None
    m = _BEARER_RE.match(authorization or "")
    if m is None:
        raise ApiError(401, "auth_required", "Vui lòng đăng nhập để tiếp tục.")
    try:
        return f"user:{st.auth.user_id(m.group(1))}"
    except AuthUnavailable:
        log.exception("Clerk keys unavailable")
        msg = "Chưa kiểm tra được đăng nhập, vui lòng thử lại."
        raise ApiError(503, "auth_unavailable", msg) from None
    except AuthError as exc:
        log.info("rejected session token: %s", exc)
        msg = "Phiên đăng nhập không hợp lệ, vui lòng đăng nhập lại."
        raise ApiError(401, "invalid_token", msg) from None


def get_owner(
    st: Annotated[AppState, Depends(get_state)],
    authorization: Annotated[str | None, Header(include_in_schema=False)] = None,
    x_client_id: Annotated[str | None, Header(alias=CLIENT_HEADER, include_in_schema=False)] = None,
) -> str:
    """FastAPI dependency: the signed-in user, else ``client:<id>`` / the public bucket."""
    if st.auth is not None:
        return _signed_in(st, authorization)
    if x_client_id is None:
        return PUBLIC_OWNER
    if not _CLIENT_RE.match(x_client_id):
        raise ApiError(400, "invalid_client_id", "Mã trình duyệt không hợp lệ.")
    return f"client:{x_client_id}"
