"""
External-IdP JWT passthrough tests (JWT_PUBLIC_KEY_URL): a real HTTP endpoint
serves the verification key (JWKS and PEM), RS256 bearer tokens flow through
the production _check_for_saml_and_jwt path against real Postgres.

This is deployed customer surface (gateways / Entra minting JWTs for Onyx
APIs) with no other functional coverage — these tests lock in existing-user
login, JIT provisioning, wrong-key rejection, expiry, and key rotation.
"""

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import Request
from jwt.algorithms import RSAAlgorithm  # ty: ignore[possibly-missing-import]
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import onyx.auth.jwt as jwt_module
import onyx.auth.users as users_module
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.models import User
from onyx.server.security.store import _build_env_defaults
from tests.external_dependency_unit.conftest import create_test_user


class _RSAKey:
    def __init__(self, kid: str) -> None:
        self.kid = kid
        self._private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )

    @property
    def private_pem(self) -> bytes:
        from cryptography.hazmat.primitives.serialization import (
            NoEncryption,
            PrivateFormat,
        )

        return self._private_key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )

    @property
    def public_pem(self) -> str:
        return (
            self._private_key.public_key()
            .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )

    @property
    def jwk(self) -> dict[str, Any]:
        jwk = json.loads(RSAAlgorithm.to_jwk(self._private_key.public_key()))
        jwk["kid"] = self.kid
        return jwk

    def mint_token(
        self, email: str, expires_in_seconds: int = 3600, kid: str | None = None
    ) -> str:
        now = datetime.now(timezone.utc)
        return pyjwt.encode(
            {
                "email": email,
                "iat": now,
                "exp": now + timedelta(seconds=expires_in_seconds),
            },
            self.private_pem,
            algorithm="RS256",
            headers={"kid": kid or self.kid},
        )


class _KeyServer(ThreadingHTTPServer):
    """Serves /jwks and /pem from mutable per-test state (rotation tests swap it)."""

    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _KeyRequestHandler)
        self.responses: dict[str, tuple[str, str]] = {}
        self.fetch_count = 0

    def set_key(self, key: _RSAKey) -> None:
        self.fetch_count = 0
        self.responses = {
            "/jwks": ("application/json", json.dumps({"keys": [key.jwk]})),
            "/pem": ("application/x-pem-file", key.public_pem),
        }

    def url(self, path: str) -> str:
        host, port = self.server_address[0], self.server_address[1]
        return f"http://{host}:{port}{path}"


class _KeyRequestHandler(BaseHTTPRequestHandler):
    server: _KeyServer

    def do_GET(self) -> None:
        self.server.fetch_count += 1
        response = self.server.responses.get(self.path)
        if response is None:
            self.send_error(404)
            return
        content_type, body = response
        payload = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture(scope="module")
def key_server() -> Any:
    server = _KeyServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def _reset_key_cache() -> Any:
    jwt_module._reset_public_key_cache()
    yield
    jwt_module._reset_public_key_cache()


class _FrozenClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> _FrozenClock:
    clock = _FrozenClock()
    monkeypatch.setattr(jwt_module, "time", clock)
    return clock


def _point_at(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    # Both modules read the shared security settings at call time. The URL is
    # treated as env-pinned, matching the env-configured deployment this test
    # simulates, so the local plain-http JWKS server stays fetchable.
    settings = _build_env_defaults().model_copy(update={"jwt_public_key_url": url})
    monkeypatch.setattr(jwt_module, "get_security_settings", lambda: settings)
    monkeypatch.setattr(users_module, "get_security_settings", lambda: settings)
    monkeypatch.setattr(
        jwt_module,
        "env_pinned_active_fields",
        lambda: frozenset({"jwt_public_key_url"}),
    )


async def _authenticate(token: str) -> User | None:
    request = Request(
        scope={
            "type": "http",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
    )
    async with get_async_session_context_manager() as async_session:
        return await users_module._check_for_saml_and_jwt(request, None, async_session)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize("key_path", ["/jwks", "/pem"])
async def test_bearer_jwt_authenticates_existing_user(
    db_session: Session,
    key_server: _KeyServer,
    monkeypatch: pytest.MonkeyPatch,
    key_path: str,
) -> None:
    # Precondition.
    user = create_test_user(db_session, "jwt_passthrough")
    key = _RSAKey(kid="primary")
    key_server.set_key(key)
    _point_at(monkeypatch, key_server.url(key_path))

    # Under test.
    authenticated = await _authenticate(key.mint_token(user.email))

    # Postcondition.
    assert authenticated is not None
    assert authenticated.id == user.id

    # A second request is served from the cached key material.
    authenticated_again = await _authenticate(key.mint_token(user.email))
    assert authenticated_again is not None
    assert authenticated_again.id == user.id


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_bearer_jwt_jit_provisions_unknown_user(
    db_session: Session,
    key_server: _KeyServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Precondition.
    key = _RSAKey(kid="primary")
    key_server.set_key(key)
    _point_at(monkeypatch, key_server.url("/jwks"))
    email = f"jwt_jit_{uuid4().hex[:8]}@example.com"

    # Under test.
    authenticated = await _authenticate(key.mint_token(email))

    # Postcondition: the user was created from the token, verified, and usable.
    assert authenticated is not None
    assert authenticated.email == email
    assert authenticated.is_verified
    assert authenticated.is_active

    provisioned = db_session.scalar(select(User).where(func.lower(User.email) == email))
    assert provisioned is not None
    assert provisioned.id == authenticated.id


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_token_signed_by_unknown_key_rejected(
    db_session: Session,
    key_server: _KeyServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Precondition.
    user = create_test_user(db_session, "jwt_wrong_key")
    trusted_key = _RSAKey(kid="primary")
    key_server.set_key(trusted_key)
    _point_at(monkeypatch, key_server.url("/jwks"))

    # Under test: signed by a key the server never served, claiming its kid.
    attacker_key = _RSAKey(kid="attacker")
    forged = attacker_key.mint_token(user.email, kid="primary")

    # Postcondition.
    assert await _authenticate(forged) is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_expired_token_rejected(
    db_session: Session,
    key_server: _KeyServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Precondition.
    user = create_test_user(db_session, "jwt_expired")
    key = _RSAKey(kid="primary")
    key_server.set_key(key)
    _point_at(monkeypatch, key_server.url("/jwks"))

    # Under test.
    expired = key.mint_token(user.email, expires_in_seconds=-300)

    # Postcondition.
    assert await _authenticate(expired) is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_rotated_key_refetched_without_restart(
    db_session: Session,
    key_server: _KeyServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Precondition: prime the in-process cache with the old key.
    user = create_test_user(db_session, "jwt_rotation")
    old_key = _RSAKey(kid="old")
    key_server.set_key(old_key)
    _point_at(monkeypatch, key_server.url("/jwks"))
    assert await _authenticate(old_key.mint_token(user.email)) is not None

    # Under test: the IdP rotates its signing key.
    new_key = _RSAKey(kid="new")
    key_server.set_key(new_key)

    # Postcondition: verification retries with a fresh fetch and succeeds.
    authenticated = await _authenticate(new_key.mint_token(user.email))
    assert authenticated is not None
    assert authenticated.id == user.id


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize("key_path", ["/jwks", "/pem"])
async def test_invalid_bearers_do_not_force_key_refetches(
    db_session: Session,
    key_server: _KeyServer,
    monkeypatch: pytest.MonkeyPatch,
    key_path: str,
) -> None:
    # Precondition: prime the cache with the trusted key.
    user = create_test_user(db_session, "jwt_refetch_flood")
    key = _RSAKey(kid="primary")
    key_server.set_key(key)
    _point_at(monkeypatch, key_server.url(key_path))
    assert await _authenticate(key.mint_token(user.email)) is not None
    assert key_server.fetch_count == 1

    fetch_threads: list[int] = []
    real_fetch = jwt_module._fetch_public_key_payload

    def _spy_fetch(*args: Any) -> Any:
        fetch_threads.append(threading.get_ident())
        return real_fetch(*args)

    monkeypatch.setattr(jwt_module, "_fetch_public_key_payload", _spy_fetch)

    # Under test: bearers that new keys cannot make valid never refetch.
    for _ in range(10):
        for bearer in (
            "x",
            "onyx_pat_abc",
            "on_abc",
            "a.b.c",
            key.mint_token(user.email, expires_in_seconds=-300),
        ):
            assert await _authenticate(bearer) is None
    assert key_server.fetch_count == 1

    # Under test: tokens signed by an unknown key (known and unknown kid).
    attacker_key = _RSAKey(kid="attacker")
    for _ in range(10):
        assert await _authenticate(attacker_key.mint_token(user.email)) is None
        forged = attacker_key.mint_token(user.email, kid="primary")
        assert await _authenticate(forged) is None

    # Postcondition: one rate-limited refetch at most, off the event loop, and
    # the trusted key is still usable.
    assert key_server.fetch_count <= 2
    assert threading.get_ident() not in fetch_threads
    assert await _authenticate(key.mint_token(user.email)) is not None
    assert key_server.fetch_count <= 2


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_rotated_key_accepted_after_refetch_interval(
    db_session: Session,
    key_server: _KeyServer,
    monkeypatch: pytest.MonkeyPatch,
    frozen_clock: _FrozenClock,
) -> None:
    # Precondition: a forged token has already used the refetch budget.
    user = create_test_user(db_session, "jwt_rotation_rate_limited")
    old_key = _RSAKey(kid="old")
    key_server.set_key(old_key)
    _point_at(monkeypatch, key_server.url("/jwks"))
    assert await _authenticate(old_key.mint_token(user.email)) is not None
    forged = _RSAKey(kid="attacker").mint_token(user.email, kid="old")
    assert await _authenticate(forged) is None

    # Under test: the IdP rotates its signing key.
    new_key = _RSAKey(kid="new")
    key_server.set_key(new_key)
    assert await _authenticate(new_key.mint_token(user.email)) is None
    assert key_server.fetch_count == 0

    # Postcondition: once the interval elapses, the rotated key is fetched.
    frozen_clock.now += jwt_module._PUBLIC_KEY_REFRESH_MIN_INTERVAL_SECONDS
    authenticated = await _authenticate(new_key.mint_token(user.email))
    assert authenticated is not None
    assert authenticated.id == user.id


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_idp_outage_recovers_after_failure_backoff(
    db_session: Session,
    key_server: _KeyServer,
    monkeypatch: pytest.MonkeyPatch,
    frozen_clock: _FrozenClock,
) -> None:
    # Precondition: the IdP key endpoint is down; the refetch clock is frozen.
    user = create_test_user(db_session, "jwt_idp_outage")
    key = _RSAKey(kid="primary")
    key_server.set_key(key)
    key_server.responses = {}
    _point_at(monkeypatch, key_server.url("/jwks"))
    backoff = jwt_module._PUBLIC_KEY_FETCH_FAILURE_BACKOFF_SECONDS
    forged = _RSAKey(kid="attacker").mint_token(user.email, kid="primary")

    # Under test: valid and forged tokens during the outage.
    for window in range(1, 4):
        for _ in range(10):
            assert await _authenticate(key.mint_token(user.email)) is None
            assert await _authenticate(forged) is None
        # At most one fetch per backoff window.
        assert key_server.fetch_count == window
        frozen_clock.now += backoff

    # Postcondition: once the IdP is back, a valid token is accepted after the
    # short backoff, not the long refresh interval.
    key_server.set_key(key)
    assert await _authenticate(key.mint_token(user.email)) is not None
    assert key_server.fetch_count == 1
