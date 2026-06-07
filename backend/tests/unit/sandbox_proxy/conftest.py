"""Shared stubs and factories for sandbox_proxy unit tests.

- `StaticLookup` — `SandboxIPLookup` stub keyed by source IP.
- `make_resolved_sandbox` / `make_flow` / `make_matched_actions` — value
  + mitmproxy-flow factories.
- `StubResolver` — identity resolver stub (sandbox + session) for the gate.
- `RecordingCredentialResolver` — `CredentialResolver` stub recording the
  claim/resolve calls a dispatcher made on it.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID
from uuid import uuid4

from mitmproxy import http

from onyx.db.enums import EndpointPolicy
from onyx.external_apps.matching.engine import AllMatchedActions
from onyx.external_apps.matching.engine import MatchedAction
from onyx.sandbox_proxy.addons.gate import _IdentityResolver
from onyx.sandbox_proxy.credential_injection import CredentialResolver
from onyx.sandbox_proxy.credential_injection import InjectionContext
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


class StubResolver(_IdentityResolver):
    """`_IdentityResolver` stub with canned returns (resolves sandbox + session)."""

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


class RecordingCredentialResolver(CredentialResolver):
    """`CredentialResolver` stub: configurable claim + canned headers/exception.

    Records every `(request, ctx)` claim probe and every `ctx` it was asked to
    resolve so tests can assert the dispatcher routed correctly.
    """

    def __init__(
        self,
        *,
        claims_result: bool = True,
        headers: dict[str, str] | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._claims_result = claims_result
        self._headers = headers if headers is not None else {}
        self._exc = exc
        self.claims_calls: list[tuple[http.Request, InjectionContext]] = []
        self.resolve_calls: list[InjectionContext] = []

    def claims(self, request: http.Request, ctx: InjectionContext) -> bool:
        self.claims_calls.append((request, ctx))
        return self._claims_result

    def resolve(
        self,
        request: http.Request,  # noqa: ARG002
        ctx: InjectionContext,
    ) -> dict[str, str]:
        self.resolve_calls.append(ctx)
        if self._exc is not None:
            raise self._exc
        return dict(self._headers)


def make_matched_actions(
    *,
    action_type: str = "slack.messages.write",
    display_name: str = "Post a message",
    description: str = "Post a message to a channel or conversation.",
    payload: dict[str, Any] | None = None,
    policy: EndpointPolicy = EndpointPolicy.ASK,
    external_app_id: int = 42,
    app_name: str = "Slack",
) -> AllMatchedActions:
    """Factory for single-action `AllMatchedActions` test rows."""
    return AllMatchedActions(
        actions=(
            MatchedAction(
                action_type=action_type,
                display_name=display_name,
                description=description,
                policy=policy,
            ),
        ),
        app_name=app_name,
        external_app_id=external_app_id,
        payload=payload if payload is not None else {},
    )
