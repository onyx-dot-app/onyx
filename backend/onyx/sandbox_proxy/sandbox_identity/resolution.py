"""Source-IP -> sandbox identity + in-band session resolution.

`IdentityResolver` splits resolution in two so non-gated traffic (npm install,
apt update) can flow once the pod is identified, while only gated traffic needs
a resolvable session:

- `resolve_sandbox()` — pod IP -> sandbox + user + tenant; enforces "only known
  sandbox pods may egress".
- `resolve_session_by_id()` — validate the in-band session tag against its owner
  to route the approval card.
- `resolve_chat_session()` — validate the tag of a command of a chat.

There is deliberately no most-recent-active fallback: a gated request with no
verifiable session tag fails closed rather than routing to a guessed session.
"""

import ipaddress
from typing import Protocol
from uuid import UUID

from onyx.db.build_session import get_build_session_id_for_user
from onyx.db.chat import get_chat_session_for_user
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.sandbox import get_sandbox_owner_id
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox, SandboxIdentity
from onyx.server.features.build.configs import SANDBOX_BACKEND, SandboxBackend
from onyx.utils.logger import setup_logger

logger = setup_logger()


PeerAddress = tuple[str, int] | tuple[str, int, int, int]


def source_ip(peer: PeerAddress | None) -> str | None:
    """Normalize transport peers for sandbox identity lookup, including mapped IPv4."""
    if not peer:
        return None
    try:
        address = ipaddress.ip_address(peer[0])
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return str(address)


class SandboxIPLookup(Protocol):
    """Backend-specific IP -> SandboxIdentity resolver.

    Implementations must return `None` for unknown IPs and have
    `wait_for_initial_sync` block until the cache is populated.
    """

    def start(self) -> None: ...

    def lookup(self, src_ip: str) -> SandboxIdentity | None: ...

    def wait_for_initial_sync(self, timeout_seconds: float) -> bool: ...

    def is_synced(self) -> bool: ...

    def stop(self) -> None: ...


class SandboxIdentityResolver(Protocol):
    """Resolve sandbox ownership and verify session attribution."""

    def resolve_sandbox(self, src_ip: str) -> ResolvedSandbox | None: ...

    def resolve_session_by_id(
        self, session_id: UUID, user_id: UUID, tenant_id: str
    ) -> UUID | None: ...

    def resolve_chat_session(
        self, session_id: UUID, user_id: UUID, tenant_id: str
    ) -> UUID | None: ...


class IdentityResolver(SandboxIdentityResolver):
    def __init__(self, ip_lookup: SandboxIPLookup) -> None:
        self._ip_lookup = ip_lookup

    def resolve_sandbox(self, src_ip: str) -> ResolvedSandbox | None:
        """
        Pod IP -> owning user + tenant; `None` if IP unknown or sandbox has no
        owner.

        Session liveness is deliberately not checked here — gate the call site
        instead.
        """
        identity = self._ip_lookup.lookup(src_ip)
        if identity is None:
            return None

        with get_session_with_tenant(tenant_id=identity.tenant_id) as db:
            user_id = get_sandbox_owner_id(db, identity.sandbox_id)
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
            return get_build_session_id_for_user(db, session_id, user_id)

    def resolve_chat_session(
        self, session_id: UUID, user_id: UUID, tenant_id: str
    ) -> UUID | None:
        """Validates a chat session id that a command in the sandbox sent: a
        chat of the owner of the sandbox that is not deleted, while the owner
        is active. Deactivation keeps shared app credentials, so this check
        stops a running command of a deactivated user from using them.

        The id is the user name of the proxy URL of the command. Each chat of
        a user runs its commands as one user in one VM, so a command can send
        the id of a second chat of the same user. The gate therefore never
        gives a chat request more than the Allow actions of that chat.
        """
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            chat_session = get_chat_session_for_user(db, session_id, user_id)
            if chat_session is None or not chat_session.user.is_active:
                return None
            return chat_session.id


def build_ip_lookup() -> SandboxIPLookup:
    """Build the configured backend without importing the other backend SDK."""
    if SANDBOX_BACKEND is SandboxBackend.KUBERNETES:
        from onyx.sandbox_proxy.sandbox_identity.kubernetes import K8sInformerLookup

        return K8sInformerLookup()
    if SANDBOX_BACKEND is SandboxBackend.DOCKER:
        from onyx.sandbox_proxy.sandbox_identity.docker import DockerEventsLookup

        return DockerEventsLookup()
    raise RuntimeError(f"Unsupported SANDBOX_BACKEND={SANDBOX_BACKEND!r}.")
