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
- `aud` is exactly `sandbox-proxy`;
- the placement record puts the sandbox on that node with that generation.
"""

import re
import time
from collections.abc import Callable
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict

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
SIGNED_IDENTITY_AUDIENCE = "sandbox-proxy"
_REQUIRED_CLAIMS = ["sub", "gen", "node", "iat", "exp", "jti", "aud"]


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


class NodeSigningKey(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    key_id: str
    node_id: str
    public_key: Ed25519PublicKey


class SandboxClaims(BaseModel):
    model_config = ConfigDict(frozen=True)

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


def is_allowed_tenant_id(tenant_id: str) -> bool:
    if MULTI_TENANT:
        return validate_tenant_id(tenant_id)
    return tenant_id == POSTGRES_DEFAULT_SCHEMA


def _parse_subject(subject: object) -> tuple[str, UUID]:
    if not isinstance(subject, str):
        raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
    match = _SUBJECT_PATTERN.match(subject)
    if match is None or not is_allowed_tenant_id(match["tenant"]):
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
        payload, signing_key = decode_node_token(
            token,
            self._signing_keys,
            audience=SIGNED_IDENTITY_AUDIENCE,
            required_claims=_REQUIRED_CLAIMS,
        )
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
        check_token_times(issued_at, expires_at, self._clock())
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


def decode_node_token(
    token: str,
    signing_keys: NodeSigningKeyLookup,
    *,
    audience: str,
    required_claims: list[str],
) -> tuple[dict[str, Any], NodeSigningKey]:
    """Size, header, key lookup, EdDSA signature and `aud` checks of a token
    signed by a node key. The caller checks the claim types and times."""
    if not token or len(token) > _MAX_TOKEN_BYTES:
        raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
    key_id = header.get("kid")
    if header.get("alg") != "EdDSA" or not isinstance(key_id, str):
        raise SignedIdentityError(SignedIdentityRejection.MALFORMED)

    signing_key = signing_keys.get(key_id)
    if signing_key is None:
        raise SignedIdentityError(SignedIdentityRejection.UNKNOWN_SIGNING_KEY)

    try:
        # The caller checks the time claims against its own clock.
        payload = jwt.decode(
            token,
            key=signing_key.public_key,
            algorithms=["EdDSA"],
            audience=audience,
            options={
                "require": required_claims,
                "strict_aud": True,
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
    except (jwt.InvalidSignatureError, jwt.DecodeError):
        raise SignedIdentityError(SignedIdentityRejection.BAD_SIGNATURE)
    except jwt.PyJWTError:
        raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
    return payload, signing_key


def check_token_times(issued_at: int, expires_at: int, now: float) -> None:
    """Freshness and the lifetime cap, with `CLOCK_SKEW_SECONDS` of slack."""
    if expires_at + CLOCK_SKEW_SECONDS <= now:
        raise SignedIdentityError(SignedIdentityRejection.EXPIRED)
    if issued_at > now + CLOCK_SKEW_SECONDS:
        raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
    if expires_at <= issued_at:
        raise SignedIdentityError(SignedIdentityRejection.MALFORMED)
    if expires_at - issued_at > MAX_TOKEN_LIFETIME_SECONDS:
        raise SignedIdentityError(SignedIdentityRejection.LIFETIME_TOO_LONG)
