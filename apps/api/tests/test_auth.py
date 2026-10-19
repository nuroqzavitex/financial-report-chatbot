import base64
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from ircb_api.auth import AuthError, AuthUnavailable, ClerkAuth, frontend_api
from ircb_api.state import AppState
from jwt.exceptions import PyJWKClientConnectionError

from tests.conftest import _client, sse_events

HOST = "example-app-12.clerk.accounts.dev"
PK = "pk_test_" + base64.b64encode(f"{HOST}$".encode()).decode().rstrip("=")
ISS = f"https://{HOST}"
ORIGIN = "http://localhost:3000"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeKeys:
    """Stands in for PyJWKClient: always the test instance's public key, or a fetch failure."""

    def __init__(self, down: bool = False) -> None:
        self.down = down

    def get_signing_key_from_jwt(self, token: str) -> Any:
        if self.down:
            raise PyJWKClientConnectionError("unreachable")
        return SimpleNamespace(key=KEY.public_key())


def token(sub: str = "user_alice", key: Any = KEY, alg: str = "RS256", **over: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": sub,
        "iss": ISS,
        "iat": now,
        "nbf": now - 1,
        "exp": now + 60,
        "azp": ORIGIN,
    }
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key if alg == "RS256" else "s" * 32, algorithm=alg)


def auth(down: bool = False) -> ClerkAuth:
    return ClerkAuth(PK, [ORIGIN], keys=FakeKeys(down))


def test_frontend_api_comes_from_the_publishable_key() -> None:
    assert frontend_api(PK) == HOST
    assert auth().issuer == ISS
    for bad in ["", "sk_test_abc", "pk_test_!!!", "pk_test_" + base64.b64encode(b"no-dollar").decode()]:
        with pytest.raises(ValueError):
            frontend_api(bad)


def test_valid_token_gives_the_user_id() -> None:
    assert auth().user_id(token()) == "user_alice"
    assert auth().user_id(token(azp=None)) == "user_alice"  # azp is optional


@pytest.mark.parametrize(
    "bad",
    [
        token(exp=int(time.time()) - 60),  # expired
        token(nbf=int(time.time()) + 60),  # not yet valid
        token(iss="https://evil.clerk.accounts.dev"),
        token(azp="https://evil.example"),
        token(sts="pending"),
        token(key=OTHER_KEY),  # signed by someone else
        token(alg="HS256"),
        token(sub=None),
        "not-a-jwt",
    ],
)
def test_bad_tokens_are_rejected(bad: str) -> None:
    with pytest.raises(AuthError):
        auth().user_id(bad)


def test_unreachable_keys_are_unavailable_not_invalid() -> None:
    with pytest.raises(AuthUnavailable):
        auth(down=True).user_id(token())


@pytest.fixture
def signed_client(state: AppState) -> Iterator[TestClient]:
    state.auth = auth()
    yield from _client(state)


def bearer(sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(sub)}"}


def test_signed_out_requests_are_refused(signed_client: TestClient) -> None:
    for r in (
        signed_client.post("/v1/chat", json={"message": "x"}),
        signed_client.get("/v1/sessions"),
        signed_client.get("/v1/sessions", headers={"X-Client-Id": "alice-browser-0001"}),
    ):
        assert r.status_code == 401 and r.json()["code"] == "auth_required"
    r = signed_client.get("/v1/sessions", headers={"Authorization": f"Bearer {token(key=OTHER_KEY)}"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_token"
    assert signed_client.get("/v1/health").status_code == 200  # the report itself stays public


def test_each_account_sees_only_its_own_history(signed_client: TestClient) -> None:
    sse = sse_events(signed_client.post("/v1/chat", json={"message": "Câu của Alice"}, headers=bearer("u_a")))
    sid = sse[-1][1]["session_id"]
    assert [s["id"] for s in signed_client.get("/v1/sessions", headers=bearer("u_a")).json()["sessions"]] == [
        sid
    ]
    assert signed_client.get("/v1/sessions", headers=bearer("u_b")).json()["sessions"] == []
    assert signed_client.get(f"/v1/sessions/{sid}", headers=bearer("u_b")).status_code == 404
    r = signed_client.post("/v1/chat", json={"session_id": sid, "message": "x"}, headers=bearer("u_b"))
    assert r.status_code == 404


def test_keys_down_is_a_503(state: AppState) -> None:
    state.auth = auth(down=True)
    for c in _client(state):
        r = c.get("/v1/sessions", headers=bearer("u_a"))
        assert r.status_code == 503 and r.json()["code"] == "auth_unavailable"
