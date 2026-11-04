"""Signed sandbox identity stamped by the host-agent relay (Firecracker runtime).

A Firecracker VM has no network card: its egress reaches the proxy through the
host agent's relay, so every VM on a node shares one source IP. The relay strips
whatever `Proxy-Authorization` the VM sent and stamps an EdDSA JWT signed with
the node's key. The proxy holds node public keys only, so it can verify an
identity but never mint one.

Accept a token only if all of these hold:
- the signature verifies against a registered, unexpired key whose node matches
  the `node` claim;
- the token is fresh (`iat`/`exp`, lifetime capped) and its `jti` is unused;
- Postgres places the sandbox on that node with that generation.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from onyx.db.engine.tenant_utils import validate_tenant_id
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA

SIGNED_IDENTITY_AUTH_SCHEME = "bearer"
SESSION_HINT_HEADER = "X-Onyx-Session-Hint"
MAX_TOKEN_LIFETIME_SECONDS = 60
CLOCK_SKEW_SECONDS = 5
# Bounds header parsing work before any signature check.
_MAX_TOKEN_BYTES = 4096

_SUBJECT_PATTERN = re.compile(
    r"^spiffe://onyx/tenant/(?P<tenant>[A-Za-z0-9_-]+)/sandbox/(?P<sandbox>[0-9a-f-]{36})$"
)
_REQUIRED_CLAIMS = ["sub", "gen", "node", "iat", "exp", "jti"]


class SignedIdentityRejection(str, Enum):
    MALFORMED = "malformed"
    UNKNOWN_SIGNING_KEY = "unknown_signing_key"
    BAD_SIGNATURE = "bad_signature"
    EXPIRED = "expired"
    LIFETIME_TOO_LONG = "lifetime_too_long"
    NODE_MISMATCH = "node_mismatch"
    REPLAYED = "replayed"
    NOT_PLACED = "not_placed"


class SignedIdentityError(Exception):
    def __init__(self, reason: SignedIdentityRejection) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True)
class NodeSigningKey:
    key_id: str
    node_id: str
    public_key: Ed25519PublicKey


@dataclass(frozen=True)
class SandboxClaims:
    sandbox_id: UUID
    tenant_id: str
    node_id: str
    generation: int
    jti: str
    expires_at: int


class NodeSigningKeyLookup(Protocol):
    def get(self, key_id: str) -> NodeSigningKey | None: ...


class SandboxPlacementLookup(Protocol):
    def owner_if_placed(self, claims: SandboxClaims) -> UUID | None:
        """The owning user if the sandbox runs on `node_id` at `generation`."""
        ...


class ReplayGuard(Protocol):
    def first_use(self, claims: SandboxClaims) -> bool:
        """Record the `jti`; False if it was already used."""
        ...


def parse_signed_identity_header(header_value: str | None) -> str | None:
    """The token if the header uses the signed scheme, else None.

    None means "not a signed request" and the caller uses the IP path. A header
    that names the signed scheme but carries no token is returned as "" so the
    caller rejects it rather than falling back.
    """
    if not header_value:
        return None
    scheme, _, rest = header_value.strip().partition(" ")
    if scheme.lower() != SIGNED_IDENTITY_AUTH_SCHEME:
        return None
    return rest.strip()


def _tenant_allowed(tenant_id: str) -> bool:
    if MULTI_TENANT:
        return validate_tenant_id(tenant_id)
    return tenant_id == POSTGRES_DEFAULT_SCHEMA


def _parse_subject(subject: object) -> tuple[str, UUID]:
    if not isinstance(subject, str):
        raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
    match = _SUBJECT_PATTERN.match(subject)
    if match is None or not _tenant_allowed(match["tenant"]):
        raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
    try:
        sandbox_id = UUID(match["sandbox"])
    except ValueError:
        raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
    # Only the canonical form, so one sandbox has exactly one subject string.
    if str(sandbox_id) != match["sandbox"]:
        raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
    return match["tenant"], sandbox_id


class SignedIdentityVerifier:
    def __init__(
        self,
        signing_keys: NodeSigningKeyLookup,
        placement: SandboxPlacementLookup,
        replay_guard: ReplayGuard,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._signing_keys = signing_keys
        self._placement = placement
        self._replay_guard = replay_guard
        self._clock = clock

    def verify(self, token: str) -> tuple[SandboxClaims, UUID]:
        """Verified claims and the owning user id; raises `SignedIdentityError`."""
        claims = self.verify_claims(token)
        if not self._replay_guard.first_use(claims):
            raise SignedIdentityError(SignedIdentityRejection.REPLAYED)
        owner = self._placement.owner_if_placed(claims)
        if owner is None:
            raise SignedIdentityError(SignedIdentityRejection.NOT_PLACED)
        return claims, owner

    def verify_claims(self, token: str) -> SandboxClaims:
        """Signature, freshness and claim checks only (no replay or placement)."""
        if not token or len(token) > _MAX_TOKEN_BYTES:
            raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
        key_id = header.get("kid")
        if header.get("alg") != "EdDSA" or not isinstance(key_id, str):
            raise SignedIdentityError(SignedIdentityRejection.MALFORMED)

        signing_key = self._signing_keys.get(key_id)
        if signing_key is None:
            raise SignedIdentityError(SignedIdentityRejection.UNKNOWN_SIGNING_KEY)

        try:
            # Time claims are checked below against the injected clock.
            payload = jwt.decode(
                token,
                key=signing_key.public_key,
                algorithms=["EdDSA"],
                options={
                    "require": _REQUIRED_CLAIMS,
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                    "verify_aud": False,
                },
            )
        except (jwt.InvalidSignatureError, jwt.DecodeError):
            raise SignedIdentityError(SignedIdentityRejection.BAD_SIGNATURE)
        except jwt.PyJWTError:
            raise SignedIdentityError(SignedIdentityRejection.MALFORMED)

        now = self._clock()
        issued_at, expires_at = payload["iat"], payload["exp"]
        generation, node_id, jti = payload["gen"], payload["node"], payload["jti"]
        if (
            not isinstance(issued_at, int)
            or not isinstance(expires_at, int)
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 0
            or not isinstance(node_id, str)
            or not node_id
            or not isinstance(jti, str)
            or not jti
            or len(jti) > 128
        ):
            raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
        if expires_at + CLOCK_SKEW_SECONDS <= now:
            raise SignedIdentityError(SignedIdentityRejection.EXPIRED)
        if issued_at > now + CLOCK_SKEW_SECONDS:
            raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
        if expires_at - issued_at > MAX_TOKEN_LIFETIME_SECONDS:
            raise SignedIdentityError(SignedIdentityRejection.LIFETIME_TOO_LONG)
        if node_id != signing_key.node_id:
            raise SignedIdentityError(SignedIdentityRejection.NODE_MISMATCH)

        tenant_id, sandbox_id = _parse_subject(payload["sub"])
        return SandboxClaims(
            sandbox_id=sandbox_id,
            tenant_id=tenant_id,
            node_id=node_id,
            generation=generation,
            jti=jti,
            expires_at=expires_at,
        )
