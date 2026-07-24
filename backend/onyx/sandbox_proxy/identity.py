"""Source-IP -> sandbox identity + in-band session resolution.

`IdentityResolver` splits resolution in two so non-gated traffic (npm install,
apt update) can flow once the pod is identified, while only gated traffic needs
a resolvable session:

- `resolve_sandbox()` — pod IP -> sandbox + user + tenant; enforces "only known
  sandbox pods may egress".
- `resolve_session_by_id()` — validate the in-band session tag against its owner
  to route the approval card.

There is deliberately no most-recent-active fallback: a gated request with no
verifiable session tag fails closed rather than routing to a guessed session.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import BuildSession, Sandbox
from onyx.utils.logger import setup_logger

logger = setup_logger()


@dataclass(frozen=True)
class SandboxIdentity:
    sandbox_id: UUID
    tenant_id: str
    sandbox_name: str
    sandbox_ip: str


@dataclass(frozen=True)
class ResolvedSandbox:
    """Sandbox identity + owning user. Authorizes egress."""

    sandbox_id: UUID
    user_id: UUID
    tenant_id: str
    sandbox_name: str
    sandbox_ip: str

    def with_session(self, session_id: UUID) -> "SessionContext":
        return SessionContext(
            session_id=session_id,
            user_id=self.user_id,
            sandbox_id=self.sandbox_id,
            tenant_id=self.tenant_id,
            sandbox_name=self.sandbox_name,
            sandbox_ip=self.sandbox_ip,
        )


@dataclass(frozen=True)
class SessionContext:
    """Sandbox identity + the verified session to route the card to."""

    session_id: UUID
    user_id: UUID
    sandbox_id: UUID
    tenant_id: str
    sandbox_name: str
    sandbox_ip: str

    def without_session(self) -> ResolvedSandbox:
        """
        Inverse of `ResolvedSandbox.with_session(...)` — drops the session id.
        """
        return ResolvedSandbox(
            sandbox_id=self.sandbox_id,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            sandbox_name=self.sandbox_name,
            sandbox_ip=self.sandbox_ip,
        )


class SandboxIPLookup(Protocol):
    """Backend-specific IP -> SandboxIdentity resolver.

    Implementations must return `None` for unknown IPs and have
    `wait_for_initial_sync` block until the cache is populated.
    """

    def start(self) -> None: ...

    def lookup(self, src_ip: str) -> SandboxIdentity | None: ...

    def wait_for_identity(
        self, src_ip: str, timeout_seconds: float
    ) -> SandboxIdentity | None:
        """Resolve a cache miss while allowing the backend watcher to catch up."""
        ...

    def wait_for_initial_sync(self, timeout_seconds: float) -> bool: ...

    def is_synced(self) -> bool: ...

    def stop(self) -> None: ...


def resolve_identity_with_watcher_grace(
    *,
    backend: str,
    src_ip: str,
    timeout_seconds: float,
    lookup: Callable[[str], SandboxIdentity | None],
    read_through: Callable[[str], SandboxIdentity | None],
    cache_updated: threading.Condition,
    stop_event: threading.Event,
) -> SandboxIdentity | None:
    """Resolve a cache miss via a backend query, then a bounded watcher wait."""
    deadline = time.monotonic() + timeout_seconds

    identity = lookup(src_ip) or read_through(src_ip)
    if identity is not None:
        return identity
    if stop_event.is_set() or timeout_seconds <= 0:
        return None

    with cache_updated:
        while not stop_event.is_set():
            identity = lookup(src_ip)
            if identity is not None:
                logger.info(
                    "identity_watcher_caught_up backend=%s src_ip=%s sandbox=%s",
                    backend,
                    src_ip,
                    identity.sandbox_name,
                )
                return identity
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            cache_updated.wait(timeout=remaining)

    if stop_event.is_set():
        return None
    identity = read_through(src_ip)
    if identity is None:
        logger.warning(
            "identity_wait_timeout backend=%s src_ip=%s timeout_seconds=%s",
            backend,
            src_ip,
            timeout_seconds,
        )
    return identity


class IdentityResolver:
    def __init__(self, ip_lookup: SandboxIPLookup) -> None:
        self._ip_lookup = ip_lookup

    def resolve_sandbox(
        self, src_ip: str, *, wait_timeout_seconds: float = 0
    ) -> ResolvedSandbox | None:
        """
        Pod IP -> owning user + tenant; `None` if IP unknown or sandbox has no
        owner.

        Session liveness is deliberately not checked here — gate the call site
        instead.
        """
        identity = self._ip_lookup.lookup(src_ip)
        if identity is None and wait_timeout_seconds > 0:
            identity = self._ip_lookup.wait_for_identity(
                src_ip, timeout_seconds=wait_timeout_seconds
            )
        if identity is None:
            return None

        with get_session_with_tenant(tenant_id=identity.tenant_id) as db:
            user_id = db.scalar(
                select(Sandbox.user_id).where(Sandbox.id == identity.sandbox_id)
            )
            if user_id is None:
                return None

        return ResolvedSandbox(
            sandbox_id=identity.sandbox_id,
            user_id=user_id,
            tenant_id=identity.tenant_id,
            sandbox_name=identity.sandbox_name,
            sandbox_ip=identity.sandbox_ip,
        )

    def resolve_session_by_id(
        self, session_id: UUID, user_id: UUID, tenant_id: str
    ) -> UUID | None:
        """Validates a sandbox-supplied `BuildSession` id against its owner.

        The id arrives in-band (the `Proxy-Authorization` username, set by the
        `session-proxy-tag` opencode plugin) and is forgeable, so it is trusted
        only if its `user_id` matches the user resolved from the source IP. This
        bounds a tampered tag to the same user; mismatches fail closed.

        Status is intentionally not filtered: this is the session that
        originated the egress regardless of its current status.
        """
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            stmt = (
                select(BuildSession.id)
                .where(BuildSession.id == session_id)
                .where(BuildSession.user_id == user_id)
            )
            return db.scalar(stmt)
