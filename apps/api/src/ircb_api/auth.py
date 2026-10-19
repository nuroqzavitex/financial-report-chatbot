"""Clerk sign-in: verify the session token the web sends as ``Authorization: Bearer <token>``.

The instance's public keys (JWKS) are fetched from its Frontend API on first use and cached, so
verification is local afterwards. A token passes when its RS256 signature is the instance's, it is
inside ``exp``/``nbf`` (a few seconds of clock skew allowed), ``iss`` is the instance, ``azp`` (when
present) is one of the web origins, and the session is not ``pending``. The user id is ``sub``.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError

LEEWAY_S = 5
JWKS_CACHE_S = 3600


class AuthError(Exception):
    """The token is missing, malformed, expired or not this instance's."""


class AuthUnavailable(Exception):
    """The instance's public keys could not be fetched."""


class _KeySource(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


def frontend_api(publishable_key: str) -> str:
    """``pk_test_<base64("<frontend api host>$")>`` -> ``<frontend api host>``."""
    try:
        kind, env, encoded = publishable_key.split("_", 2)
        host = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("not a Clerk publishable key") from exc
    if kind != "pk" or env not in ("test", "live") or not host.endswith("$") or len(host) < 2:
        raise ValueError("not a Clerk publishable key")
    return host[:-1]


class ClerkAuth:
    def __init__(
        self, publishable_key: str, authorized_parties: Iterable[str], keys: _KeySource | None = None
    ) -> None:
        self.issuer = f"https://{frontend_api(publishable_key)}"
        self.parties = {p.rstrip("/") for p in authorized_parties}
        self._keys: _KeySource = keys or PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=JWKS_CACHE_S
        )

    def user_id(self, token: str) -> str:
        try:
            key = self._keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.issuer,
                leeway=LEEWAY_S,
                options={"require": ["exp", "nbf", "iss", "sub"]},
            )
        except PyJWKClientConnectionError as exc:
            raise AuthUnavailable(str(exc)) from exc
        except jwt.PyJWTError as exc:
            raise AuthError(str(exc)) from exc
        azp = claims.get("azp")
        if azp is not None and str(azp).rstrip("/") not in self.parties:
            raise AuthError("token issued for another origin")
        if claims.get("sts") == "pending":
            raise AuthError("session is pending")
        return str(claims["sub"])
