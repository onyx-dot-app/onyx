"""Shared stubs and factories for sandbox_proxy unit tests.

- `StaticLookup` — `SandboxIPLookup` stub keyed by source IP.
- `make_resolved_sandbox` / `make_flow` — value + mitmproxy-flow factories.
- `StubResolver` — identity resolver stub (sandbox + session) for the gate.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID
from uuid import uuid4

from mitmproxy import http

from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.identity import SandboxIdentity
from onyx.sandbox_proxy.identity import SandboxIPLookup

_SANDBOX_ID = UUID("11111111-1111-1111-1111-111111111111")


class StaticLookup(SandboxIPLookup):
    """`SandboxIPLookup` Protocol stub with a fixed in-memory map.

    Two shapes: `StaticLookup({ip: identity, ...})` keys by source IP;
    `StaticLookup.single(identity_or_none)` returns the same identity for any IP.
    """

    def __init__(
        self,
        cache: dict[str, SandboxIdentity] | None = None,
        *,
        single: SandboxIdentity | None = None,
        single_mode: bool = False,
    ) -> None:
        self._cache: dict[str, SandboxIdentity] = cache or {}
        self._single = single
        self._single_mode = single_mode

    @classmethod
    def single(cls, identity: SandboxIdentity | None) -> "StaticLookup":
        """Return `identity` for any source IP (or `None` for none)."""
        return cls(single=identity, single_mode=True)

    def start(self) -> None:
        return None

    def lookup(self, src_ip: str) -> SandboxIdentity | None:
        if self._single_mode:
            return self._single
        return self._cache.get(src_ip)

    def wait_for_initial_sync(
        self,
        timeout_seconds: float,  # noqa: ARG002
    ) -> bool:
        return True

    def is_synced(self) -> bool:
        return True

    def stop(self) -> None:
        return None


def make_resolved_sandbox(
    *,
    user_id: UUID | None = None,
    tenant_id: str = "public",
    sandbox_id: UUID = _SANDBOX_ID,
    sandbox_name: str = "sandbox-aaaa1111",
    sandbox_ip: str = "10.0.0.1",
) -> ResolvedSandbox:
    return ResolvedSandbox(
        sandbox_id=sandbox_id,
        user_id=user_id if user_id is not None else uuid4(),
        tenant_id=tenant_id,
        sandbox_name=sandbox_name,
        sandbox_ip=sandbox_ip,
    )


def make_flow(
    *,
    host: str = "slack.com",
    peername: tuple[str, int] | None = ("10.0.0.1", 12345),
    raw_content: bytes | None = b"{}",
    port: int = 443,
    method: str = "POST",
    path_components: tuple[str, ...] = (),
    conn_id: str = "conn-default",
    proxy_auth: str | None = None,
    headers: dict[str, str] | None = None,
) -> http.HTTPFlow:
    flow = MagicMock(spec=http.HTTPFlow)
    flow.client_conn = MagicMock()
    flow.client_conn.peername = peername
    flow.client_conn.id = conn_id
    flow.request = MagicMock()
    flow.request.host = host
    flow.request.port = port
    flow.request.method = method
    flow.request.path_components = path_components
    flow.request.raw_content = raw_content
    flow.request.stream = False
    # Real dict (not MagicMock) so `.get(...)` and the metadata flag lookups
    # behave; seed arbitrary headers and/or the session tag.
    request_headers = dict(headers) if headers is not None else {}
    if proxy_auth is not None:
        request_headers["Proxy-Authorization"] = proxy_auth
    flow.request.headers = request_headers
    flow.response = None
    flow.metadata = {}
    return flow


class StubResolver:
    """`SessionResolver` stub with canned returns (resolves sandbox + session)."""

    def __init__(
        self,
        *,
        sandbox: ResolvedSandbox | None = None,
        sandbox_exc: Exception | None = None,
        session_by_id: UUID | None = None,
        session_by_id_exc: Exception | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._sandbox_exc = sandbox_exc
        self._session_by_id = session_by_id
        self._session_by_id_exc = session_by_id_exc
        self.resolve_sandbox_calls = 0
        self.resolve_session_by_id_calls: list[tuple[UUID, UUID, str]] = []

    def resolve_sandbox(
        self,
        src_ip: str,  # noqa: ARG002
    ) -> ResolvedSandbox | None:
        self.resolve_sandbox_calls += 1
        if self._sandbox_exc is not None:
            raise self._sandbox_exc
        return self._sandbox

    def resolve_session_by_id(
        self,
        session_id: UUID,
        user_id: UUID,
        tenant_id: str,
    ) -> UUID | None:
        self.resolve_session_by_id_calls.append((session_id, user_id, tenant_id))
        if self._session_by_id_exc is not None:
            raise self._session_by_id_exc
        return self._session_by_id
