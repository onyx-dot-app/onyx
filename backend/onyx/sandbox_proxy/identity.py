"""Source-IP → sandbox identity (+ optional active session) resolution.

The IP-to-sandbox step is backend-specific (`SandboxIPLookup`
Protocol). Downstream resolution lives on `IdentityResolver`, split
into two phases:

* `resolve_sandbox()` — pod IP → sandbox + user + tenant. Used for
  every request to enforce "only known sandbox pods may egress".
* `resolve_active_session()` — user → active `BuildSession`. Only
  needed when a request is gated and we need somewhere to route the
  approval card.

Splitting the two lets non-gated traffic (npm install, apt update,
etc.) flow whenever the pod is identified, even if the user has no
ACTIVE session at that moment — startup-time and inter-session
egress shouldn't depend on session liveness.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import BuildSessionStatus
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.utils.logger import setup_logger

logger = setup_logger()


@dataclass(frozen=True)
class SandboxIdentity:
    """Pod-level identity. Available for any identified sandbox pod."""

    sandbox_id: UUID
    tenant_id: str
    sandbox_name: str
    sandbox_ip: str


@dataclass(frozen=True)
class ResolvedSandbox:
    """Sandbox identity + the user that owns it.

    Returned by `resolve_sandbox()`. Sufficient to authorize egress
    and (when combined with `resolve_active_session()`) to mint an
    approval row.
    """

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
    """Sandbox identity + active session id.

    Built from `ResolvedSandbox.with_session(session_id)` once the gate
    has confirmed both that the request is gated and that there's an
    active session to route the approval card to.
    """

    session_id: UUID
    user_id: UUID
    sandbox_id: UUID
    tenant_id: str
    sandbox_name: str
    sandbox_ip: str


class SandboxIPLookup(Protocol):
    """Backend-specific IP → SandboxIdentity resolver.

    Implementations must return `None` for unknown IPs and block
    callers on `wait_for_initial_sync` until the cache is populated.
    """

    def start(self) -> None: ...

    def lookup(self, src_ip: str) -> SandboxIdentity | None: ...

    def wait_for_initial_sync(self, timeout_seconds: float) -> bool: ...

    def is_synced(self) -> bool: ...

    def stop(self) -> None: ...


DBSessionFactory = Callable[[str], AbstractContextManager[Session]]


def _default_session_factory(tenant_id: str) -> AbstractContextManager[Session]:
    return get_session_with_tenant(tenant_id=tenant_id)


class IdentityResolver:
    def __init__(
        self,
        ip_lookup: SandboxIPLookup,
        db_session_factory: DBSessionFactory | None = None,
    ) -> None:
        self._ip_lookup = ip_lookup
        self._session_factory = (
            db_session_factory
            if db_session_factory is not None
            else _default_session_factory
        )

    def resolve_sandbox(self, src_ip: str) -> ResolvedSandbox | None:
        """Pod IP → owning user + tenant. No session lookup.

        Returns `None` for an unknown source IP or a sandbox row with
        no owning user. Active-session liveness is deliberately not
        checked here — gate the call site instead.
        """
        identity = self._ip_lookup.lookup(src_ip)
        if identity is None:
            return None

        with self._session_factory(identity.tenant_id) as db:
            user_id = self._fetch_sandbox_user(db, identity.sandbox_id)
            if user_id is None:
                return None

        return ResolvedSandbox(
            sandbox_id=identity.sandbox_id,
            user_id=user_id,
            tenant_id=identity.tenant_id,
            sandbox_name=identity.sandbox_name,
            sandbox_ip=identity.sandbox_ip,
        )

    def resolve_active_session(self, user_id: UUID, tenant_id: str) -> UUID | None:
        """Most-recently-active `BuildSession` for the user, or None.

        Called only on gated requests, where we need a session_id to
        route the approval card. This is the fallback heuristic; prefer
        `resolve_session_by_id` when the request carries an in-band tag.
        """
        with self._session_factory(tenant_id) as db:
            return self._fetch_active_session(db, user_id)

    def resolve_session_by_id(
        self, session_id: UUID, user_id: UUID, tenant_id: str
    ) -> UUID | None:
        """Validate a sandbox-supplied `BuildSession` id against its owner.

        The session id arrives in-band as the `Proxy-Authorization`
        username (set by the `session-proxy-tag` opencode plugin from the
        session's workspace path). It is trusted only after confirming the
        row exists AND its `user_id` matches the user resolved from the
        source IP — which the sandbox cannot forge. This bounds a tampered
        or stale tag to the same user (no cross-user routing); on any
        mismatch the caller falls back to `resolve_active_session`.

        Status is intentionally not filtered: this id came from the
        session that actually originated the egress, so it is the correct
        routing target regardless of its current status.
        """
        with self._session_factory(tenant_id) as db:
            stmt = (
                select(BuildSession.id)
                .where(BuildSession.id == session_id)
                .where(BuildSession.user_id == user_id)
            )
            return db.scalar(stmt)

    def _fetch_sandbox_user(self, db: Session, sandbox_id: UUID) -> UUID | None:
        stmt = select(Sandbox.user_id).where(Sandbox.id == sandbox_id)
        return db.scalar(stmt)

    def _fetch_active_session(self, db: Session, user_id: UUID) -> UUID | None:
        stmt = (
            select(BuildSession.id)
            .where(BuildSession.user_id == user_id)
            .where(BuildSession.status == BuildSessionStatus.ACTIVE)
            .order_by(BuildSession.last_activity_at.desc())
            .limit(1)
        )
        return db.scalar(stmt)
