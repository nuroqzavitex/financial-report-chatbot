"""Who owns a conversation: the request's owner id, matched exactly against the session's owner.

Without sign-in the web sends a random per-browser id in ``X-Client-Id``; it separates one
browser's history from another's but is not authentication (anyone holding the id can read
those sessions). A request without the header shares one public bucket. Prefixes keep the
namespaces apart, so a later signed-in owner (``user:...``) never collides with a browser id.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Header

from ircb_api.errors import ApiError

CLIENT_HEADER = "X-Client-Id"
PUBLIC_OWNER = "public"
_CLIENT_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def get_owner(
    x_client_id: Annotated[str | None, Header(alias=CLIENT_HEADER, include_in_schema=False)] = None,
) -> str:
    """FastAPI dependency: ``client:<id>`` for a well-formed browser id, else the public bucket."""
    if x_client_id is None:
        return PUBLIC_OWNER
    if not _CLIENT_RE.match(x_client_id):
        raise ApiError(400, "invalid_client_id", "Mã trình duyệt không hợp lệ.")
    return f"client:{x_client_id}"
