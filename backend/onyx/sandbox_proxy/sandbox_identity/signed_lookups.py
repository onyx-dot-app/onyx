"""Cache and Postgres backed lookups for `SignedIdentityVerifier`."""

import threading
import time
from collections.abc import Callable
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.microvm.registry import (
    get_node_signing_key,
    get_sandbox_placement,
)
from onyx.sandbox_proxy.sandbox_identity.signed import (
    CLOCK_SKEW_SECONDS,
    NodeSigningKey,
    NodeSigningKeyLookup,
    ReplayGuard,
    SandboxClaims,
    SandboxPlacementLookup,
)
from onyx.server.features.build.db.sandbox import get_sandbox_by_id

# Bounds how long a rotated or expired key keeps verifying.
_SIGNING_KEY_CACHE_TTL_SECONDS = 30.0
# Unknown key ids are cached too, so forged `kid`s cannot drive cache load; the
# cap keeps that memo bounded.
_SIGNING_KEY_CACHE_MAX_ENTRIES = 4096
_REPLAY_KEY_PREFIX = "sandbox_proxy:signed_jti"

CacheFactory = Callable[[str], CacheBackend]


class CachedNodeSigningKeyLookup(NodeSigningKeyLookup):
    def __init__(
        self,
        shared_cache: Callable[[], CacheBackend],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._shared_cache = shared_cache
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, NodeSigningKey | None]] = {}

    def get(self, key_id: str) -> NodeSigningKey | None:
        now = self._clock()
        with self._lock:
            cached = self._entries.get(key_id)
        if cached is not None and cached[0] > now:
            return cached[1]

        registered = get_node_signing_key(self._shared_cache(), key_id)
        signing_key = (
            None
            if registered is None
            else NodeSigningKey(
                key_id=key_id,
                node_id=registered.node_id,
                public_key=Ed25519PublicKey.from_public_bytes(registered.public_key),
            )
        )
        with self._lock:
            if len(self._entries) >= _SIGNING_KEY_CACHE_MAX_ENTRIES:
                self._entries.clear()
            self._entries[key_id] = (now + _SIGNING_KEY_CACHE_TTL_SECONDS, signing_key)
        return signing_key


class CacheSandboxPlacementLookup(SandboxPlacementLookup):
    def __init__(self, cache_factory: CacheFactory) -> None:
        self._cache_factory = cache_factory

    def owner_if_placed(self, claims: SandboxClaims) -> UUID | None:
        placement = get_sandbox_placement(
            self._cache_factory(claims.tenant_id), claims.sandbox_id
        )
        if (
            placement is None
            or placement.node_id != claims.node_id
            or placement.generation != claims.generation
        ):
            return None
        with get_session_with_tenant(tenant_id=claims.tenant_id) as db:
            sandbox = get_sandbox_by_id(db, claims.sandbox_id)
            return None if sandbox is None else sandbox.user_id


class CacheReplayGuard(ReplayGuard):
    def __init__(
        self,
        cache_factory: CacheFactory,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._cache_factory = cache_factory
        self._clock = clock

    def first_use(self, claims: SandboxClaims) -> bool:
        # Keep the marker until the token can no longer pass the expiry check.
        ttl = max(1, int(claims.expires_at + CLOCK_SKEW_SECONDS - self._clock()) + 1)
        return self._cache_factory(claims.tenant_id).set_if_absent(
            f"{_REPLAY_KEY_PREFIX}:{claims.node_id}:{claims.jti}", "1", ex=ttl
        )
