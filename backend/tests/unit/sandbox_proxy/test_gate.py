"""Unit tests for the GateAddon mitmproxy addon.

External dependencies (`SandboxIdentityResolver`, `RequestEvaluator`, `CacheFactory`)
are stubbed via small Protocol implementations; `get_session_with_tenant` is
patched per test.

The race arbiter (`_claim_expired_or_read_winner`) is covered against a
real Postgres row in
`external_dependency_unit/sandbox_proxy/test_gate_claim_arbiter.py`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from contextlib import nullcontext
from dataclasses import dataclass
from typing import AbstractSet, Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from mitmproxy import connection, http
from mitmproxy.proxy import server_hooks
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from onyx.cache.interface import CacheBackend
from onyx.db.enums import (
    ActionPolicy,
    ApprovalDecidedVia,
    ApprovalDecision,
    GatedAppKind,
)
from onyx.external_apps.matching.engine import (
    AllMatchedActions,
    GatedTarget,
    MatchedAction,
)
from onyx.sandbox_proxy import destination_policy
from onyx.sandbox_proxy.addons import gate
from onyx.sandbox_proxy.addons.gate import GateAddon, ParkedApprovals
from onyx.sandbox_proxy.credential_injection import (
    CredentialInjectionDispatcher,
    CredentialResolver,
    CredentialUnavailableError,
)
from onyx.sandbox_proxy.destination_policy import parse_destination_policy
from onyx.sandbox_proxy.errors import SandboxProxyError
from onyx.sandbox_proxy.models import (
    DestinationPolicyConfig,
    InjectionOutcome,
    McpProtocolRequest,
)
from onyx.sandbox_proxy.request_evaluator import RequestEvaluator
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox, SessionContext
from tests.unit.sandbox_proxy.conftest import (
    RecordingCredentialResolver,
    StubResolver,
    make_flow,
    make_matched_actions,
    make_resolved_sandbox,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubMatcher(RequestEvaluator):
    def __init__(
        self,
        *,
        result: AllMatchedActions | McpProtocolRequest | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._result = result
        self._exc = exc
        self.calls = 0

    def evaluate(
        self,
        request: http.Request,  # noqa: ARG002
        tenant_id: str,  # noqa: ARG002
        user_id: UUID,  # noqa: ARG002
    ) -> AllMatchedActions | McpProtocolRequest | None:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._result


def _noop_cache_factory(tenant_id: str) -> Any:  # noqa: ARG001
    raise AssertionError("cache factory unexpectedly used")


def _ctx(
    *,
    tenant_id: str = "public",
    session_id: UUID | None = None,
    user_id: UUID | None = None,
) -> SessionContext:
    return SessionContext(
        session_id=session_id if session_id is not None else uuid4(),
        user_id=user_id if user_id is not None else uuid4(),
        sandbox_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=tenant_id,
        sandbox_name="sandbox-aaaa1111",
        sandbox_ip="10.0.0.1",
    )


@pytest.fixture(autouse=True)
def _patch_gate_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate opens tenant sessions via `gate.get_session_with_tenant`.
    Unit tests treat the session as an opaque collaborator; persistence and
    transaction behavior are covered by external-dependency tests."""
    monkeypatch.setattr(
        gate,
        "get_session_with_tenant",
        lambda **_kwargs: nullcontext(MagicMock(spec=Session)),
    )
    monkeypatch.setattr(
        destination_policy.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo("93.184.216.34"),
    )
    monkeypatch.setattr(gate, "pin_destination", lambda _host, _port, _address: None)
    monkeypatch.setattr(
        gate, "get_active_scheduled_task_context", lambda _db, _session: None
    )
    monkeypatch.setattr(
        gate,
        "resolve_action_policies",
        lambda _db, *, catalog_policies, **_kwargs: catalog_policies,
    )
    monkeypatch.setattr(
        gate.action_approval,
        "get_action_approval",
        lambda _db, _id: MagicMock(
            session_id=UUID(_TAG_UUID),
            decision=ApprovalDecision.APPROVED,
            decided_via=ApprovalDecidedVia.USER,
        ),
    )
    # The stub sessions can't answer the target → gated_app_id lookup.
    monkeypatch.setattr(gate, "get_gated_app_id", lambda _db, _kind, _target_id: 1)
    monkeypatch.setattr(
        gate.action_approval,
        "list_session_grant_action_approvals",
        lambda _db, *, session_id, gated_app_id: [],  # noqa: ARG005
    )


def _build(
    *,
    resolver: StubResolver,
    matcher: _StubMatcher,
    cache_factory: Any = _noop_cache_factory,
    credential_resolvers: list[CredentialResolver] | None = None,
    policy: DestinationPolicyConfig | None = None,
) -> GateAddon:
    return GateAddon(
        identity=resolver,
        request_evaluator=matcher,
        destination_policy=policy
        if policy is not None
        else parse_destination_policy(""),
        cache_factory=cache_factory,
        proxy_instance_id="proxy-test",
        credential_dispatcher=CredentialInjectionDispatcher(
            credential_resolvers if credential_resolvers is not None else []
        ),
    )


def _assert_403(flow: http.HTTPFlow, expected_code: SandboxProxyError) -> None:
    assert flow.response is not None
    assert flow.response.status_code == 403
    content = flow.response.content
    assert content is not None
    body = json.loads(content)
    assert body["error"] == expected_code.value
    assert body["message"]


_MATCH = make_matched_actions(payload={"text": "hi"})
_MATCH_MCP = AllMatchedActions(
    actions=_MATCH.actions,
    target=GatedTarget(
        kind=GatedAppKind.MCP_SERVER,
        id=73,
        app_name="Linear MCP",
    ),
    payload=_MATCH.payload,
)
_MATCH_MULTI_ASK = AllMatchedActions(
    actions=(
        MatchedAction(
            action_type="slack.messages.write",
            display_name="Post a message",
            description="Post a message to a channel or conversation.",
            policy=ActionPolicy.ASK,
        ),
        MatchedAction(
            action_type="slack.files.upload",
            display_name="Upload a file",
            description="Upload a file to a channel or conversation.",
            policy=ActionPolicy.ASK,
        ),
    ),
    target=GatedTarget(kind=GatedAppKind.EXTERNAL_APP, id=42, app_name="Slack"),
    payload={"text": "hi"},
)
_MATCH_ALWAYS = make_matched_actions(
    action_type="slack.channels.read", policy=ActionPolicy.ALWAYS
)
_MATCH_DENY = make_matched_actions(payload={"text": "hi"}, policy=ActionPolicy.DENY)


# ---------------------------------------------------------------------------
# _resolve_and_match — fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_and_match_no_source_ip_fails_closed() -> None:
    resolver = StubResolver()
    matcher = _StubMatcher(result=_MATCH)
    addon = _build(resolver=resolver, matcher=matcher)
    flow = make_flow(peername=None)

    result = await addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, SandboxProxyError.UNIDENTIFIED_SANDBOX)
    # Short-circuited before resolver / matcher ran.
    assert resolver.resolve_sandbox_calls == 0
    assert matcher.calls == 0


@pytest.mark.parametrize(
    "resolver_kwargs",
    [
        {"sandbox": None},
        {"sandbox_exc": RuntimeError("db down")},
    ],
    ids=["returns_none", "raises"],
)
@pytest.mark.asyncio
async def test_resolve_and_match_sandbox_resolution_fails_closed(
    resolver_kwargs: dict[str, Any],
) -> None:
    """Absent pod and DB blip during resolution both fail closed."""
    resolver = StubResolver(**resolver_kwargs)
    matcher = _StubMatcher(result=_MATCH)
    addon = _build(resolver=resolver, matcher=matcher)
    flow = make_flow()

    result = await addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, SandboxProxyError.UNIDENTIFIED_SANDBOX)
    assert matcher.calls == 0


@pytest.mark.asyncio
async def test_resolve_and_match_body_at_cap_is_allowed() -> None:
    resolver = StubResolver(sandbox=make_resolved_sandbox())
    matcher = _StubMatcher(result=None)
    addon = _build(resolver=resolver, matcher=matcher)
    # Built inside the test so the multi-MB allocation is deferred past collection.
    flow = make_flow(raw_content=b"\x00" * gate.PARSER_MAX_BODY_BYTES)

    result = await addon._resolve_and_match(flow)

    assert result is None
    assert flow.response is None
    assert matcher.calls == 1


@pytest.mark.parametrize("oversize", [False, True], ids=["streamed", "oversize"])
@pytest.mark.asyncio
async def test_resolve_and_match_body_too_large_fails_closed(
    oversize: bool,
) -> None:
    """Streamed (None) and oversize bodies both fail closed."""
    resolver = StubResolver(sandbox=make_resolved_sandbox())
    matcher = _StubMatcher(result=_MATCH)
    addon = _build(resolver=resolver, matcher=matcher)
    # Built here, not at module scope, so the over-cap allocation only happens
    # for the test that needs it.
    raw_content = b"\x00" * (gate.PARSER_MAX_BODY_BYTES + 1) if oversize else None
    flow = make_flow(raw_content=raw_content)

    result = await addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, SandboxProxyError.BODY_TOO_LARGE)
    assert matcher.calls == 0


@pytest.mark.asyncio
async def test_resolve_and_match_no_tag_fails_closed() -> None:
    """Identified pod, no session tag: fail closed with no fallback, so
    the session lookup is never attempted."""
    resolver = StubResolver(sandbox=make_resolved_sandbox())
    matcher = _StubMatcher(result=_MATCH)
    addon = _build(resolver=resolver, matcher=matcher)
    flow = make_flow()  # no proxy_auth

    result = await addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, SandboxProxyError.NO_ACTIVE_SESSION)
    assert resolver.resolve_session_by_id_calls == []


# ---------------------------------------------------------------------------
# _resolve_and_match — fail-open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_and_match_matcher_returns_none_fails_open() -> None:
    """Non-gated traffic: matcher returns None → forwarded; the off-catalog
    dispatcher invocation runs with `matched_actions=None` so host-only resolvers can
    still claim by host."""
    sandbox = make_resolved_sandbox()
    resolver = StubResolver(sandbox=sandbox)
    matcher = _StubMatcher(result=None)
    spy = RecordingCredentialResolver(claims_result=False)
    addon = _build(resolver=resolver, matcher=matcher, credential_resolvers=[spy])
    flow = make_flow()

    result = await addon._resolve_and_match(flow)

    assert result is None
    assert flow.response is None  # forwarded
    assert resolver.resolve_session_by_id_calls == []
    # The off-catalog dispatch IS wired — the resolver was probed with matched_actions=None.
    assert len(spy.claims_calls) == 1
    _request, ctx = spy.claims_calls[0]
    assert ctx.matched_actions is None
    assert ctx.sandbox is sandbox


@pytest.mark.asyncio
async def test_resolve_and_match_off_catalog_pass_through_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """High-volume package-manager traffic should forward without producing a
    proxy event line or extracting the session tag."""
    resolver = StubResolver(sandbox=make_resolved_sandbox())
    matcher = _StubMatcher(result=None)
    addon = _build(
        resolver=resolver,
        matcher=matcher,
        credential_resolvers=[RecordingCredentialResolver(claims_result=False)],
    )
    flow = make_flow(host="registry.npmjs.org", proxy_auth=_basic_auth(_TAG_UUID))

    with caplog.at_level(logging.DEBUG, logger="onyx.utils.logger"):
        result = await addon._resolve_and_match(flow)

    assert result is None
    assert flow.response is None
    messages = [record.getMessage() for record in caplog.records]
    assert not any(message.startswith("egress_") for message in messages)
    assert not any(message.startswith("session_tag_resolved") for message in messages)
    assert resolver.resolve_session_by_id_calls == []


@pytest.mark.asyncio
async def test_resolve_and_match_matcher_failure_blocks_before_credentials() -> None:
    """A failed recognition must not authorize credential injection."""
    resolver = StubResolver(sandbox=make_resolved_sandbox())
    matcher = _StubMatcher(exc=RuntimeError("matcher boom"))
    spy = RecordingCredentialResolver(claims_result=False)
    addon = _build(resolver=resolver, matcher=matcher, credential_resolvers=[spy])
    flow = make_flow()

    result = await addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, SandboxProxyError.INTERNAL_ERROR)
    assert spy.claims_calls == []


# ---------------------------------------------------------------------------
# _resolve_and_match — verdict enforcement (ALWAYS / DENY)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_and_match_always_requires_session() -> None:
    """Even automatic actions resolve the session before forwarding."""
    resolver = StubResolver(
        sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
    )
    addon = _build(
        resolver=resolver,
        matcher=_StubMatcher(result=_MATCH_ALWAYS),
        # No-claim resolver -> dispatcher returns PASS_THROUGH, leaves the
        # flow forwarded with no response.
        credential_resolvers=[RecordingCredentialResolver(claims_result=False)],
    )
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    result = await addon._resolve_and_match(flow)

    assert result is not None
    assert result[1] == _MATCH_ALWAYS
    assert flow.response is None
    assert resolver.resolve_session_by_id_calls


@pytest.mark.asyncio
async def test_resolve_and_match_deny_blocks_with_403() -> None:
    """DENY blocks outright with a policy_denied 403, with a verified session."""
    resolver = StubResolver(
        sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
    )
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH_DENY))
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    result = await addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, SandboxProxyError.POLICY_DENIED)
    assert resolver.resolve_session_by_id_calls


# ---------------------------------------------------------------------------
# request() — the gate's contract, one test per verdict path
#
#   ALWAYS      -> straight through (forward) + inject; NO approval pipeline
#   off-catalog -> straight through (forward); NO inject; NO approval pipeline
#   DENY        -> blocked (403); NO inject; NO approval pipeline
#   ASK         -> approval pipeline runs, THEN:
#                    APPROVED          -> forward + inject
#                    REJECTED/EXPIRED  -> blocked (403); NO inject
#
# Each test drives the real `request()` entry point and asserts all three
# observable dimensions: forwarded vs blocked, approval pipeline ran, injected.
# ---------------------------------------------------------------------------


@dataclass
class _PipelineSpy:
    """Records the approval pipeline + dispatcher so a test can read the path."""

    persisted: list[tuple[SessionContext, AllMatchedActions]]
    awaited: list[AllMatchedActions]
    # (matched_actions, sandbox_user_id, sandbox_tenant_id) — captured off the
    # InjectionContext the dispatcher was handed.
    dispatched: list[tuple[AllMatchedActions | None, UUID, str]]

    @property
    def approval_ran(self) -> bool:
        return bool(self.persisted)


def _spy_pipeline(
    addon: GateAddon,
    monkeypatch: pytest.MonkeyPatch,
    *,
    decision: ApprovalDecision | None = None,
) -> _PipelineSpy:
    """Stub the approval pipeline (persist + await) and capture dispatch
    invocations so each verdict path can be read end-to-end.

    `decision` is what the (stubbed) approval wait resolves to — only the ASK
    path reaches it.
    """
    spy = _PipelineSpy(persisted=[], awaited=[], dispatched=[])

    def _persist(ctx: SessionContext, matched_actions: AllMatchedActions) -> UUID:
        spy.persisted.append((ctx, matched_actions))
        return uuid4()

    async def _await(
        _aid: UUID, _ctx: SessionContext, matched_actions: AllMatchedActions
    ) -> ApprovalDecision | None:
        spy.awaited.append(matched_actions)
        return decision

    def _dispatch(
        flow: http.HTTPFlow,  # noqa: ARG001
        *,
        sandbox: ResolvedSandbox,
        matched_actions: AllMatchedActions | None,
    ) -> InjectionOutcome:
        spy.dispatched.append((matched_actions, sandbox.user_id, sandbox.tenant_id))
        return InjectionOutcome.INJECTED

    monkeypatch.setattr(addon, "_persist_approval_row", _persist)
    monkeypatch.setattr(addon, "_await_decision", _await)
    monkeypatch.setattr(addon, "_dispatch_injection_or_block", _dispatch)
    return spy


@pytest.mark.asyncio
async def test_always_goes_straight_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """ALWAYS: forwarded immediately with credentials, no approval prompt."""
    sandbox = make_resolved_sandbox()
    addon = _build(
        resolver=StubResolver(sandbox=sandbox, session_by_id=UUID(_TAG_UUID)),
        matcher=_StubMatcher(result=_MATCH_ALWAYS),
    )
    spy = _spy_pipeline(addon, monkeypatch)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    await addon.request(flow)

    assert flow.response is None  # forwarded
    assert not spy.approval_ran  # straight through — no prompt
    assert spy.dispatched == [(_MATCH_ALWAYS, sandbox.user_id, sandbox.tenant_id)]


@pytest.mark.asyncio
async def test_deny_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """DENY: blocked with a 403, no approval prompt, NO dispatch."""
    addon = _build(
        resolver=StubResolver(
            sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
        ),
        matcher=_StubMatcher(result=_MATCH_DENY),
    )
    spy = _spy_pipeline(addon, monkeypatch)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    await addon.request(flow)

    _assert_403(flow, SandboxProxyError.POLICY_DENIED)
    assert not spy.approval_ran
    assert spy.dispatched == []


@pytest.mark.asyncio
async def test_ask_approved_forwards_after_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ASK: runs the approval pipeline; on APPROVED forwards + dispatches."""
    user_id = uuid4()
    sandbox = make_resolved_sandbox(user_id=user_id)
    resolver = StubResolver(sandbox=sandbox, session_by_id=UUID(_TAG_UUID))
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))
    spy = _spy_pipeline(addon, monkeypatch, decision=ApprovalDecision.APPROVED)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    await addon.request(flow)

    assert spy.approval_ran  # required approval
    assert spy.awaited == [_MATCH]
    assert flow.response is None  # forwarded after approval
    assert spy.dispatched == [(_MATCH, user_id, sandbox.tenant_id)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision, expected_code",
    [
        (ApprovalDecision.REJECTED, SandboxProxyError.USER_REJECTED),
        (ApprovalDecision.EXPIRED, SandboxProxyError.NOT_AUTHORIZED),
    ],
)
async def test_ask_denied_blocks(
    monkeypatch: pytest.MonkeyPatch,
    decision: ApprovalDecision,
    expected_code: SandboxProxyError,
) -> None:
    """ASK: runs the approval pipeline; on REJECTED/EXPIRED blocks, no dispatch."""
    resolver = StubResolver(
        sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
    )
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))
    spy = _spy_pipeline(addon, monkeypatch, decision=decision)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    await addon.request(flow)

    assert spy.approval_ran  # required approval before blocking
    _assert_403(flow, expected_code)
    assert spy.dispatched == []


# ---------------------------------------------------------------------------
# request() — retained session approvals
# ---------------------------------------------------------------------------


_RUN_ID = UUID("55555555-5555-5555-5555-555555555555")
# make_matched_actions defaults external_app_id=42.
_GRANTED_APP_ID = 42
_GRANTED_MCP_SERVER_ID = 73


def _spy_approval_insert(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture insert_action_approval kwargs (the DB session is a MagicMock)."""
    inserted: list[dict[str, Any]] = []
    rows: dict[UUID, Any] = {}

    def _fake_insert(db: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        inserted.append(kwargs)
        row = MagicMock(**kwargs)
        row.approval_id = uuid4()
        rows[row.approval_id] = row
        return row

    monkeypatch.setattr(
        gate.action_approval,
        "get_action_approval",
        lambda _db, approval_id: rows.get(approval_id),
    )
    monkeypatch.setattr(gate.action_approval, "insert_action_approval", _fake_insert)
    return inserted


class _SessionGrantCache:
    def __init__(
        self,
        granted: bool | list[bool] = False,
        *,
        granted_action_types: AbstractSet[str] | None = None,
    ) -> None:
        self._grant_results = [granted] if isinstance(granted, bool) else list(granted)
        self._granted_action_types = granted_action_types
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, str | bytes | int | float, int | None]] = []
        self.expire_calls: list[tuple[str, int]] = []

    def get(self, key: str) -> bytes | None:
        self.get_calls.append(key)
        if self._granted_action_types is not None:
            granted = any(
                key.endswith(f":{action_type}")
                for action_type in self._granted_action_types
            )
        elif len(self._grant_results) > 1:
            granted = self._grant_results.pop(0)
        else:
            granted = self._grant_results[0]
        return b"approval-id" if granted else None

    def expire(self, key: str, seconds: int) -> None:
        self.expire_calls.append((key, seconds))

    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> None:
        self.set_calls.append((key, value, ex))


@pytest.mark.asyncio
async def test_session_grant_skips_park_without_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    sandbox = make_resolved_sandbox(user_id=user_id)
    cache = _SessionGrantCache(granted=True)
    resolver = StubResolver(sandbox=sandbox, session_by_id=UUID(_TAG_UUID))
    addon = _build(
        resolver=resolver,
        matcher=_StubMatcher(result=_MATCH),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )
    spy = _spy_pipeline(addon, monkeypatch)
    inserted = _spy_approval_insert(monkeypatch)
    notified: list[dict[str, Any]] = []
    monkeypatch.setattr(gate, "create_notification", lambda **kw: notified.append(kw))
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    await addon.request(flow)

    assert flow.response is None
    assert not spy.approval_ran
    assert spy.awaited == []
    assert spy.dispatched == [(_MATCH, user_id, sandbox.tenant_id)]
    assert len(inserted) == 1
    assert inserted[0]["decision"] == ApprovalDecision.APPROVED
    assert inserted[0]["decided_via"] == ApprovalDecidedVia.SESSION_GRANT
    assert notified == []
    assert cache.get_calls
    assert cache.expire_calls


@pytest.mark.asyncio
async def test_session_grant_db_fallback_hydrates_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    sandbox = make_resolved_sandbox(user_id=user_id)
    cache = _SessionGrantCache(granted=False)
    resolver = StubResolver(sandbox=sandbox, session_by_id=UUID(_TAG_UUID))
    addon = _build(
        resolver=resolver,
        matcher=_StubMatcher(result=_MATCH),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )
    spy = _spy_pipeline(addon, monkeypatch)
    inserted = _spy_approval_insert(monkeypatch)
    source_approval_id = uuid4()
    grant_source = MagicMock()
    grant_source.approval_id = source_approval_id
    grant_source.actions = [action.model_dump(mode="json") for action in _MATCH.actions]

    monkeypatch.setattr(
        gate.action_approval,
        "list_session_grant_action_approvals",
        lambda _db, *, session_id, gated_app_id: [grant_source],  # noqa: ARG005
    )
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    await addon.request(flow)

    assert flow.response is None
    assert not spy.approval_ran
    assert spy.awaited == []
    assert spy.dispatched == [(_MATCH, user_id, sandbox.tenant_id)]
    assert len(inserted) == 1
    assert inserted[0]["decision"] == ApprovalDecision.APPROVED
    assert inserted[0]["decided_via"] == ApprovalDecidedVia.SESSION_GRANT
    assert cache.get_calls
    assert any(str(source_approval_id) == value for _key, value, _ex in cache.set_calls)


@pytest.mark.asyncio
async def test_partial_session_grant_still_parks_multi_action_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _SessionGrantCache(granted_action_types={"slack.messages.write"})
    resolver = StubResolver(
        sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
    )
    addon = _build(
        resolver=resolver,
        matcher=_StubMatcher(result=_MATCH_MULTI_ASK),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )
    spy = _spy_pipeline(addon, monkeypatch, decision=ApprovalDecision.REJECTED)
    inserted = _spy_approval_insert(monkeypatch)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    await addon.request(flow)

    assert spy.approval_ran
    assert spy.awaited == [_MATCH_MULTI_ASK]
    _assert_403(flow, SandboxProxyError.USER_REJECTED)
    assert inserted == []
    assert cache.get_calls
    assert cache.expire_calls == []


@pytest.mark.asyncio
async def test_session_grant_recheck_after_persist_skips_park(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    sandbox = make_resolved_sandbox(user_id=user_id)
    cache = _SessionGrantCache(granted=[False, True])
    resolver = StubResolver(sandbox=sandbox, session_by_id=UUID(_TAG_UUID))
    addon = _build(
        resolver=resolver,
        matcher=_StubMatcher(result=_MATCH),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )
    spy = _spy_pipeline(addon, monkeypatch, decision=ApprovalDecision.REJECTED)
    approval_id = uuid4()

    def _persist(ctx: SessionContext, _match: AllMatchedActions) -> UUID:
        addon._parked.add(ctx.tenant_id, approval_id)
        return approval_id

    monkeypatch.setattr(addon, "_persist_approval_row", _persist)
    decisions: list[dict[str, Any]] = []

    def _record_decision(_db: Any, **kwargs: Any) -> object:
        decisions.append(kwargs)
        return object()

    monkeypatch.setattr(gate.action_approval, "try_record_decision", _record_decision)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    await addon.request(flow)

    assert flow.response is None
    assert spy.persisted == []
    assert spy.awaited == []
    assert spy.dispatched == [(_MATCH, user_id, sandbox.tenant_id)]
    assert addon._parked.snapshot() == []
    assert decisions == [
        {
            "approval_id": approval_id,
            "decision": ApprovalDecision.APPROVED,
            "decided_via": ApprovalDecidedVia.SESSION_GRANT,
        }
    ]


# ---------------------------------------------------------------------------
# _resolve_and_match — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_and_match_happy_path_promotes_session() -> None:
    user_id = uuid4()
    session_id = UUID(_TAG_UUID)
    sandbox = make_resolved_sandbox(user_id=user_id)
    resolver = StubResolver(sandbox=sandbox, session_by_id=session_id)
    matcher = _StubMatcher(result=_MATCH)
    addon = _build(resolver=resolver, matcher=matcher)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    result = await addon._resolve_and_match(flow)

    assert result is not None
    ctx, matched_actions = result
    assert matched_actions == _MATCH
    assert ctx.session_id == session_id
    assert ctx.user_id == user_id
    assert ctx.tenant_id == sandbox.tenant_id
    assert ctx.sandbox_id == sandbox.sandbox_id
    assert flow.response is None


# ---------------------------------------------------------------------------
# In-band session tag — Proxy-Authorization parsing
# ---------------------------------------------------------------------------


def _basic_auth(username: str, password: str = "") -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


_TAG_UUID = "44444444-4444-4444-4444-444444444444"


@pytest.mark.parametrize(
    "header, expected",
    [
        (_basic_auth(_TAG_UUID), _TAG_UUID),  # id-only tag (empty password)
        (_basic_auth(_TAG_UUID, "secret"), _TAG_UUID),  # password ignored
        (
            f"Basic {base64.b64encode(_TAG_UUID.encode()).decode()}",
            _TAG_UUID,
        ),  # no colon
        (None, None),
        ("", None),
        ("Bearer abc", None),  # not basic
        ("Basic !!!notbase64!!!", None),  # undecodable
        ("Basic", None),  # missing token
    ],
)
def test_parse_proxy_auth_username(header: str | None, expected: str | None) -> None:
    assert gate._parse_proxy_auth_username(header) == expected


@pytest.mark.asyncio
async def test_http_connect_caches_tag_and_client_disconnected_evicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gate, "resolve_destination", lambda *_args, **_kwargs: ("8.8.8.8",)
    )
    addon = _build(
        resolver=StubResolver(sandbox=make_resolved_sandbox()), matcher=_StubMatcher()
    )
    flow = make_flow(conn_id="conn-xyz", proxy_auth=_basic_auth(_TAG_UUID))

    await addon.http_connect(flow)
    assert addon._conn_session_tags == {"conn-xyz": _TAG_UUID}

    addon.client_disconnected(flow.client_conn)
    assert addon._conn_session_tags == {}


@pytest.mark.asyncio
async def test_http_connect_ignores_missing_or_garbled_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gate, "resolve_destination", lambda *_args, **_kwargs: ("8.8.8.8",)
    )
    addon = _build(
        resolver=StubResolver(sandbox=make_resolved_sandbox()), matcher=_StubMatcher()
    )
    await addon.http_connect(make_flow(conn_id="c1"))  # no Proxy-Authorization
    await addon.http_connect(make_flow(conn_id="c2", proxy_auth="Bearer nope"))
    assert addon._conn_session_tags == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("peer_ip", ["10.0.0.99", "2600:ffff:ffff::99"])
async def test_http_connect_rejects_unknown_peer(
    monkeypatch: pytest.MonkeyPatch, peer_ip: str
) -> None:
    monkeypatch.setattr(
        gate, "resolve_destination", lambda *_args, **_kwargs: ("8.8.8.8",)
    )
    addon: GateAddon = _build(resolver=StubResolver(), matcher=_StubMatcher())
    flow: http.HTTPFlow = make_flow(
        method="CONNECT", peername=(peer_ip, 12345), proxy_auth=_basic_auth(_TAG_UUID)
    )

    await addon.http_connect(flow)

    _assert_403(flow, SandboxProxyError.UNIDENTIFIED_SANDBOX)
    assert addon._conn_session_tags == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("peer", [None, ("not-an-ip", 12345)])
async def test_http_connect_rejects_missing_peer(
    monkeypatch: pytest.MonkeyPatch, peer: tuple[str, int] | None
) -> None:
    monkeypatch.setattr(
        gate, "resolve_destination", lambda *_args, **_kwargs: ("8.8.8.8",)
    )
    resolver: StubResolver = StubResolver(sandbox=make_resolved_sandbox())
    addon: GateAddon = _build(resolver=resolver, matcher=_StubMatcher())
    flow: http.HTTPFlow = make_flow(method="CONNECT", peername=peer)

    await addon.http_connect(flow)

    _assert_403(flow, SandboxProxyError.UNIDENTIFIED_SANDBOX)
    assert resolver.resolve_sandbox_calls == 0


@pytest.mark.asyncio
async def test_http_connect_rejects_identity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gate, "resolve_destination", lambda *_args, **_kwargs: ("8.8.8.8",)
    )
    addon: GateAddon = _build(
        resolver=StubResolver(sandbox_exc=RuntimeError("database unavailable")),
        matcher=_StubMatcher(),
    )
    flow: http.HTTPFlow = make_flow(method="CONNECT")

    await addon.http_connect(flow)

    _assert_403(flow, SandboxProxyError.UNIDENTIFIED_SANDBOX)


# ---------------------------------------------------------------------------
# Destination policy integration — internal-egress guard
# ---------------------------------------------------------------------------


def _addrinfo(*ips: str) -> list[Any]:
    return [(2, 1, 6, "", (ip, 0)) for ip in ips]


def _server_hook_data(host: str, port: int) -> server_hooks.ServerConnectionHookData:
    server = connection.Server(address=(host, port))
    server.sni = host  # mitmproxy sets sni to the hostname before server_connect
    return server_hooks.ServerConnectionHookData(
        server=server, client=connection.Client(peername=("c", 0), sockname=("s", 0))
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("sni", ["example.com", "tls.example.com", None])
async def test_server_connect_pins_public_address_and_preserves_sni(
    sni: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = MagicMock()
    monkeypatch.setattr(gate, "pin_destination", pin)
    addon: GateAddon = _build(resolver=StubResolver(), matcher=_StubMatcher())
    data: server_hooks.ServerConnectionHookData = _server_hook_data("example.com", 443)
    data.server.sni = sni

    await addon.server_connect(data)

    assert data.server.error is None
    assert data.server.address == ("example.com", 443)
    pin.assert_called_once_with("example.com", 443, ("93.184.216.34",))
    assert data.server.sni == (sni if sni is not None else "example.com")


@pytest.mark.asyncio
async def test_server_connect_fails_closed_without_upstream_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_host: str, _port: int, _addresses: tuple[str, ...]) -> None:
        raise RuntimeError("Missing upstream loop")

    monkeypatch.setattr(gate, "pin_destination", unavailable)
    addon: GateAddon = _build(resolver=StubResolver(), matcher=_StubMatcher())
    data: server_hooks.ServerConnectionHookData = _server_hook_data("example.com", 443)
    await addon.server_connect(data)
    assert data.server.error == "destination_blocked: upstream resolver unavailable"


@pytest.mark.asyncio
async def test_server_connect_blocks_dns_rebind_after_connect_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver: StubResolver = StubResolver(sandbox=make_resolved_sandbox())
    addon: GateAddon = _build(resolver=resolver, matcher=_StubMatcher())
    flow: http.HTTPFlow = make_flow(host="rebind.example", method="CONNECT")
    await addon.http_connect(flow)
    assert flow.response is None

    monkeypatch.setattr(
        destination_policy.socket,
        "getaddrinfo",
        lambda *_a, **_k: _addrinfo("10.1.2.3"),
    )
    data: server_hooks.ServerConnectionHookData = _server_hook_data(
        "rebind.example", 443
    )
    await addon.server_connect(data)

    assert data.server.error is not None
    assert data.server.address == ("rebind.example", 443)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "CONNECT"])
async def test_configured_global_internal_cidr_denied_before_identity(
    method: str,
) -> None:
    resolver: StubResolver = StubResolver(sandbox=make_resolved_sandbox())
    matcher: _StubMatcher = _StubMatcher()
    addon: GateAddon = _build(
        resolver=resolver,
        matcher=matcher,
        policy=parse_destination_policy("", ["2600:ffff:ffff::/64"]),
    )
    flow: http.HTTPFlow = make_flow(host="2600:ffff:ffff::2", method=method)

    if method == "CONNECT":
        await addon.http_connect(flow)
    else:
        await addon.request(flow)

    _assert_403(flow, SandboxProxyError.DESTINATION_BLOCKED)
    assert resolver.resolve_sandbox_calls == 0
    assert matcher.calls == 0


# ---------------------------------------------------------------------------
# _resolve_and_match — exact in-band session resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_and_match_exact_tag_on_http_request() -> None:
    """Plain-HTTP: Proxy-Authorization rides on the request; a verified
    tag routes to that exact session."""
    user_id = uuid4()
    tagged_id = UUID(_TAG_UUID)
    sandbox = make_resolved_sandbox(user_id=user_id)
    resolver = StubResolver(sandbox=sandbox, session_by_id=tagged_id)
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    result = await addon._resolve_and_match(flow)

    assert result is not None
    ctx, _match = result
    assert ctx.session_id == tagged_id
    assert resolver.resolve_session_by_id_calls == [
        (tagged_id, user_id, sandbox.tenant_id)
    ]


@pytest.mark.asyncio
async def test_resolve_and_match_exact_tag_on_https_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTPS: the tag rode on the CONNECT (captured via http_connect)
    and is read back off the connection, not the MITM'd request."""
    monkeypatch.setattr(
        gate, "resolve_destination", lambda *_args, **_kwargs: ("8.8.8.8",)
    )
    user_id = uuid4()
    tagged_id = UUID(_TAG_UUID)
    sandbox = make_resolved_sandbox(user_id=user_id)
    resolver = StubResolver(sandbox=sandbox, session_by_id=tagged_id)
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))

    connect_flow = make_flow(conn_id="conn-1", proxy_auth=_basic_auth(_TAG_UUID))
    await addon.http_connect(connect_flow)
    # Decrypted request has no Proxy-Authorization of its own.
    request_flow = make_flow(conn_id="conn-1")

    result = await addon._resolve_and_match(request_flow)

    assert result is not None
    ctx, _match = result
    assert ctx.session_id == tagged_id


@pytest.mark.asyncio
async def test_resolve_and_match_unverified_tag_fails_closed() -> None:
    """Tag doesn't resolve to one of this user's sessions (stale /
    foreign / tampered): fail closed, no fallback."""
    sandbox = make_resolved_sandbox()
    resolver = StubResolver(sandbox=sandbox, session_by_id=None)
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    result = await addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, SandboxProxyError.NO_ACTIVE_SESSION)
    assert len(resolver.resolve_session_by_id_calls) == 1


@pytest.mark.asyncio
async def test_resolve_and_match_malformed_tag_fails_closed() -> None:
    """A non-UUID username fails closed without hitting the DB."""
    resolver = StubResolver(sandbox=make_resolved_sandbox())
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))
    flow = make_flow(proxy_auth=_basic_auth("not-a-uuid"))

    result = await addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, SandboxProxyError.NO_ACTIVE_SESSION)
    assert resolver.resolve_session_by_id_calls == []


@pytest.mark.asyncio
async def test_resolve_and_match_session_by_id_db_error_fails_closed() -> None:
    """A DB blip validating the tag fails closed, not silently forward."""
    resolver = StubResolver(
        sandbox=make_resolved_sandbox(), session_by_id_exc=RuntimeError("db down")
    )
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))

    result = await addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, SandboxProxyError.NO_ACTIVE_SESSION)
    assert len(resolver.resolve_session_by_id_calls) == 1


@pytest.mark.asyncio
async def test_request_strips_proxy_authorization_before_forward() -> None:
    """The in-band tag must never reach the origin: a forwarded request
    has Proxy-Authorization stripped."""
    resolver = StubResolver(sandbox=make_resolved_sandbox())
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=None))
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))
    assert "Proxy-Authorization" in flow.request.headers

    await addon.request(flow)

    assert flow.response is None  # forwarded
    assert "Proxy-Authorization" not in flow.request.headers


# ---------------------------------------------------------------------------
# responseheaders — stream all responses (don't buffer streaming bodies)
# ---------------------------------------------------------------------------


def test_responseheaders_streams_response_body() -> None:
    """Responses are never gated, so they must stream through unbuffered —
    otherwise long SSE bodies (the agent's streamed LLM completions) are held
    until complete and can truncate."""
    addon = _build(resolver=StubResolver(), matcher=_StubMatcher())
    flow = make_flow()
    flow.response = MagicMock()
    flow.response.stream = False

    addon.responseheaders(flow)

    assert flow.response.stream is True


# ---------------------------------------------------------------------------
# _dispatch_injection_or_block — credential dispatcher wired into the gate
# ---------------------------------------------------------------------------


def test_dispatch_injection_writes_resolved_headers() -> None:
    """A claiming resolver's headers overwrite whatever the sandbox shipped —
    the real secret lives only in the proxy."""
    spy = RecordingCredentialResolver(
        claims_result=True, headers={"Authorization": "Bearer real-secret"}
    )
    addon = _build(
        resolver=StubResolver(),
        matcher=_StubMatcher(),
        credential_resolvers=[spy],
    )
    flow = make_flow()
    flow.request.headers["Authorization"] = "sandbox-placeholder"
    sandbox = make_resolved_sandbox()

    outcome = addon._dispatch_injection_or_block(
        flow, sandbox=sandbox, matched_actions=_MATCH_ALWAYS
    )

    assert outcome is InjectionOutcome.INJECTED
    assert flow.response is None  # forwarded
    assert flow.request.headers["Authorization"] == "Bearer real-secret"
    assert len(spy.resolve_calls) == 1
    seen = spy.resolve_calls[0]
    assert seen.sandbox is sandbox
    assert seen.matched_actions is _MATCH_ALWAYS


def test_dispatch_injection_pass_through_forwards_untouched() -> None:
    """No resolver claims: forward, don't 403, don't modify headers."""
    addon = _build(
        resolver=StubResolver(),
        matcher=_StubMatcher(),
        credential_resolvers=[RecordingCredentialResolver(claims_result=False)],
    )
    flow = make_flow()
    flow.request.headers["X-Pod-Side"] = "preserve"

    outcome = addon._dispatch_injection_or_block(
        flow, sandbox=make_resolved_sandbox(), matched_actions=_MATCH_ALWAYS
    )

    assert outcome is InjectionOutcome.PASS_THROUGH
    assert flow.response is None
    assert flow.request.headers["X-Pod-Side"] == "preserve"


def test_dispatch_injection_credential_unavailable_blocks_with_403() -> None:
    """A claiming resolver that can't render fails closed at the gate boundary
    — the request never forwards with the sandbox's own headers."""
    addon = _build(
        resolver=StubResolver(),
        matcher=_StubMatcher(),
        credential_resolvers=[
            RecordingCredentialResolver(
                claims_result=True,
                exc=CredentialUnavailableError("no PAT for sandbox"),
            )
        ],
    )
    flow = make_flow()

    outcome = addon._dispatch_injection_or_block(
        flow, sandbox=make_resolved_sandbox(), matched_actions=_MATCH_ALWAYS
    )

    assert outcome is InjectionOutcome.BLOCKED
    _assert_403(flow, SandboxProxyError.CREDENTIAL_ERROR)


def test_dispatch_injection_resolver_exception_blocks_with_403() -> None:
    """Any other resolver error is also fail-closed — never a silent forward."""
    addon = _build(
        resolver=StubResolver(),
        matcher=_StubMatcher(),
        credential_resolvers=[
            RecordingCredentialResolver(claims_result=True, exc=RuntimeError("db blip"))
        ],
    )
    flow = make_flow()

    outcome = addon._dispatch_injection_or_block(
        flow, sandbox=make_resolved_sandbox(), matched_actions=_MATCH_ALWAYS
    )

    assert outcome is InjectionOutcome.BLOCKED
    _assert_403(flow, SandboxProxyError.CREDENTIAL_ERROR)


# ---------------------------------------------------------------------------
# ParkedApprovals
# ---------------------------------------------------------------------------


def test_parked_approvals_snapshot_is_independent_of_source() -> None:
    """snapshot() must be iterable while the loop mutates `_by_tenant`;
    pin the deep-copy semantic so a shallow refactor fails here."""
    parked = ParkedApprovals()
    id_a = uuid4()
    id_b = uuid4()
    id_c = uuid4()
    parked.add("tenant-1", id_a)
    parked.add("tenant-1", id_b)
    parked.add("tenant-2", id_c)

    snap_before = parked.snapshot()

    new_id = uuid4()
    parked.add("tenant-1", new_id)
    parked.remove("tenant-2", id_c)

    # snap_before reflects the state at the time it was taken.
    snap_dict_before = dict(snap_before)
    assert snap_dict_before["tenant-1"] == {id_a, id_b}
    assert snap_dict_before["tenant-2"] == {id_c}

    snap_after = dict(parked.snapshot())
    assert snap_after["tenant-1"] == {id_a, id_b, new_id}
    # tenant-2 went empty so its entry was cleaned up (see next test).
    assert "tenant-2" not in snap_after


def test_parked_approvals_remove_last_cleans_tenant_entry() -> None:
    """Empty per-tenant sets are deleted so the snapshot can't grow
    unbounded over the proxy's lifetime."""
    parked = ParkedApprovals()
    approval_id = uuid4()
    parked.add("tenant-1", approval_id)
    assert dict(parked.snapshot()) == {"tenant-1": {approval_id}}

    parked.remove("tenant-1", approval_id)

    assert parked.snapshot() == []

    # Removing again is a no-op (must not raise or re-create the entry).
    parked.remove("tenant-1", approval_id)
    assert parked.snapshot() == []


# ---------------------------------------------------------------------------
# _await_decision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_await_decision_wake_received_returns_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wake before timeout returns its decision; parked entry cleared."""
    approval_id = uuid4()
    ctx = _ctx(tenant_id="tenant-1")

    async def _fake_wait_for_wake(
        _approval_id: UUID, timeout: int, _cache: Any
    ) -> ApprovalDecision | None:
        assert timeout == gate.SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
        return ApprovalDecision.APPROVED

    monkeypatch.setattr(gate.approval_cache, "wait_for_wake", _fake_wait_for_wake)

    cache = MagicMock(spec=CacheBackend)
    addon = _build(
        resolver=StubResolver(),
        matcher=_StubMatcher(),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )
    addon._parked.add(ctx.tenant_id, approval_id)

    decision = await addon._await_decision(approval_id, ctx, _MATCH)

    assert decision == ApprovalDecision.APPROVED
    assert addon._parked.snapshot() == []


@pytest.mark.asyncio
async def test_await_decision_timeout_claims_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wait returns None → claim EXPIRED via the race arbiter."""
    approval_id = uuid4()
    ctx = _ctx(tenant_id="tenant-1")

    async def _fake_wait_for_wake(
        _approval_id: UUID, _timeout: int, _cache: Any
    ) -> ApprovalDecision | None:
        return None

    monkeypatch.setattr(gate.approval_cache, "wait_for_wake", _fake_wait_for_wake)

    cache = MagicMock(spec=CacheBackend)
    addon = _build(
        resolver=StubResolver(),
        matcher=_StubMatcher(),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )
    addon._parked.add(ctx.tenant_id, approval_id)

    claim_calls: list[tuple[UUID, str]] = []

    def _fake_claim(aid: UUID, tid: str) -> ApprovalDecision:
        claim_calls.append((aid, tid))
        return ApprovalDecision.EXPIRED

    monkeypatch.setattr(addon, "_claim_expired_or_read_winner", _fake_claim)

    decision = await addon._await_decision(approval_id, ctx, _MATCH)

    assert decision == ApprovalDecision.EXPIRED
    assert claim_calls == [(approval_id, ctx.tenant_id)]
    assert addon._parked.snapshot() == []


@pytest.mark.asyncio
async def test_await_decision_cancelled_claims_expired_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Socket closed mid-wait: claim EXPIRED (terminal audit row) and
    re-raise so mitmproxy releases the flow."""
    approval_id = uuid4()
    ctx = _ctx(tenant_id="tenant-1")

    async def _fake_wait_for_wake(
        _approval_id: UUID, _timeout: int, _cache: Any
    ) -> ApprovalDecision | None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(gate.approval_cache, "wait_for_wake", _fake_wait_for_wake)

    cache = MagicMock(spec=CacheBackend)
    addon = _build(
        resolver=StubResolver(),
        matcher=_StubMatcher(),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )
    addon._parked.add(ctx.tenant_id, approval_id)

    claim_calls: list[tuple[UUID, str]] = []

    def _fake_claim(aid: UUID, tid: str) -> ApprovalDecision:
        claim_calls.append((aid, tid))
        return ApprovalDecision.EXPIRED

    monkeypatch.setattr(addon, "_claim_expired_or_read_winner", _fake_claim)

    with pytest.raises(asyncio.CancelledError):
        await addon._await_decision(approval_id, ctx, _MATCH)

    assert claim_calls == [(approval_id, ctx.tenant_id)]
    assert addon._parked.snapshot() == []


# ---------------------------------------------------------------------------
# drain_inflight
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_inflight_walks_parked_per_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drain wakes every parked approval on its own tenant's cache, never
    cross-tenant, and leaves `_parked` untouched (removal is owned by
    `_await_decision.finally`)."""
    cache_t1 = MagicMock(spec=CacheBackend)
    cache_t2 = MagicMock(spec=CacheBackend)
    per_tenant_caches: dict[str, CacheBackend] = {
        "tenant-1": cache_t1,
        "tenant-2": cache_t2,
    }

    addon = _build(
        resolver=StubResolver(),
        matcher=_StubMatcher(),
        cache_factory=lambda tenant_id: per_tenant_caches[tenant_id],
    )

    t1_a = uuid4()
    t1_b = uuid4()
    t2_a = uuid4()
    addon._parked.add("tenant-1", t1_a)
    addon._parked.add("tenant-1", t1_b)
    addon._parked.add("tenant-2", t2_a)

    parked_before = dict(addon._parked.snapshot())

    monkeypatch.setattr(
        addon,
        "_claim_expired_or_read_winner",
        lambda _aid, _tid: ApprovalDecision.EXPIRED,
    )

    send_wake_calls: list[tuple[UUID, ApprovalDecision, CacheBackend]] = []

    def _fake_send_wake(aid: UUID, decision: ApprovalDecision, cache: Any) -> None:
        send_wake_calls.append((aid, decision, cache))

    monkeypatch.setattr(gate.approval_cache, "send_wake", _fake_send_wake)

    await addon.drain_inflight()

    waked_ids = {aid for aid, _decision, _cache in send_wake_calls}
    assert waked_ids == {t1_a, t1_b, t2_a}

    # Each id waked on its own tenant's cache, no cross-contamination.
    for aid, _decision, cache in send_wake_calls:
        if aid in (t1_a, t1_b):
            assert cache is cache_t1, "tenant-1 approval waked on wrong cache"
        else:
            assert cache is cache_t2, "tenant-2 approval waked on wrong cache"

    # Drain must not remove from `_parked` (owned by _await_decision.finally).
    assert dict(addon._parked.snapshot()) == parked_before


@pytest.mark.asyncio
async def test_drain_inflight_completes_when_inflight_set_empty() -> None:
    """Nothing parked or inflight: drain returns immediately."""
    cache_factory_calls: list[str] = []

    def _tracking_cache_factory(tenant_id: str) -> CacheBackend:
        cache_factory_calls.append(tenant_id)
        return MagicMock(spec=CacheBackend)

    addon = _build(
        resolver=StubResolver(),
        matcher=_StubMatcher(),
        cache_factory=_tracking_cache_factory,
    )

    assert addon._parked.snapshot() == []
    assert addon._inflight_tasks == set()

    # Low timeout so a regression to an unbounded wait fails fast.
    await asyncio.wait_for(addon.drain_inflight(), timeout=1.0)

    # Cache factory not consulted: nothing parked to walk.
    assert addon._parked.snapshot() == []
    assert addon._inflight_tasks == set()
    assert cache_factory_calls == []


# ---------------------------------------------------------------------------
# _terminalize_after_unhandled_error
# ---------------------------------------------------------------------------


def test_terminalize_happy_path_writes_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup claims a terminal decision and forwards it via send_wake.
    The wake carries the arbiter's decision (APPROVED here if the API
    won the race), not unconditionally EXPIRED."""
    approval_id = uuid4()
    cache = MagicMock(spec=CacheBackend)
    addon = _build(
        resolver=StubResolver(),
        matcher=_StubMatcher(),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )

    monkeypatch.setattr(
        addon,
        "_claim_expired_or_read_winner",
        lambda _aid, _tid: ApprovalDecision.APPROVED,
    )

    wake_calls: list[tuple[UUID, ApprovalDecision]] = []

    def _fake_send_wake(aid: UUID, decision: ApprovalDecision, _cache: Any) -> None:
        wake_calls.append((aid, decision))

    monkeypatch.setattr(gate.approval_cache, "send_wake", _fake_send_wake)

    addon._terminalize_after_unhandled_error(approval_id, "tenant-1")

    assert wake_calls == [(approval_id, ApprovalDecision.APPROVED)]


def test_terminalize_db_failure_skips_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the claim raises, there's no decision to forward, so send_wake
    must not be called; the exception is swallowed."""
    approval_id = uuid4()
    cache = MagicMock(spec=CacheBackend)
    addon = _build(
        resolver=StubResolver(),
        matcher=_StubMatcher(),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )

    def _claim_raises(aid: UUID, tid: str) -> ApprovalDecision:  # noqa: ARG001
        raise RuntimeError("db blip")

    monkeypatch.setattr(addon, "_claim_expired_or_read_winner", _claim_raises)

    wake_count = 0

    def _fake_send_wake(_aid: UUID, _decision: ApprovalDecision, _cache: Any) -> None:
        nonlocal wake_count
        wake_count += 1

    monkeypatch.setattr(gate.approval_cache, "send_wake", _fake_send_wake)

    # Should not raise.
    addon._terminalize_after_unhandled_error(approval_id, "tenant-1")

    assert wake_count == 0


def test_terminalize_wake_failure_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """send_wake raising must not propagate; the parked BLPOP times out
    and re-reads the already-terminal row from Postgres."""
    approval_id = uuid4()
    cache = MagicMock(spec=CacheBackend)
    addon = _build(
        resolver=StubResolver(),
        matcher=_StubMatcher(),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )

    monkeypatch.setattr(
        addon,
        "_claim_expired_or_read_winner",
        lambda _aid, _tid: ApprovalDecision.EXPIRED,
    )

    def _wake_raises(_aid: UUID, _decision: ApprovalDecision, _cache: Any) -> None:
        raise RedisError("wake failed")

    monkeypatch.setattr(gate.approval_cache, "send_wake", _wake_raises)

    # Should not raise.
    addon._terminalize_after_unhandled_error(approval_id, "tenant-1")


@pytest.mark.asyncio
async def test_auto_approval_without_session_is_blocked() -> None:
    addon = _build(
        resolver=StubResolver(sandbox=make_resolved_sandbox()),
        matcher=_StubMatcher(result=_MATCH_ALWAYS),
    )
    flow = make_flow()
    await addon.request(flow)
    _assert_403(flow, SandboxProxyError.NO_ACTIVE_SESSION)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [ActionPolicy.ASK, ActionPolicy.DENY])
async def test_personal_setting_restricts_catalog_auto_approval(
    monkeypatch: pytest.MonkeyPatch, policy: ActionPolicy
) -> None:
    monkeypatch.setattr(
        gate,
        "resolve_action_policies",
        lambda _db, *, catalog_policies, **_kwargs: dict.fromkeys(
            catalog_policies, policy
        ),
    )
    addon = _build(
        resolver=StubResolver(
            sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
        ),
        matcher=_StubMatcher(result=_MATCH_ALWAYS),
    )
    spy = _spy_pipeline(addon, monkeypatch, decision=ApprovalDecision.REJECTED)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))
    await addon.request(flow)
    assert spy.dispatched == []
    assert spy.approval_ran is (policy is ActionPolicy.ASK)
    _assert_403(
        flow,
        SandboxProxyError.USER_REJECTED
        if policy is ActionPolicy.ASK
        else SandboxProxyError.POLICY_DENIED,
    )


@pytest.mark.asyncio
async def test_task_settings_are_read_live_without_grant_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    monkeypatch.setattr(
        gate,
        "get_active_scheduled_task_context",
        lambda _db, _session: (_RUN_ID, task_id),
    )
    current_policy = ActionPolicy.ALWAYS
    owners: list[UUID | None] = []

    def resolve(
        _db: Session,
        *,
        catalog_policies: dict[str, ActionPolicy],
        scheduled_task_id: UUID | None,
        **_kwargs: object,
    ) -> dict[str, ActionPolicy]:
        owners.append(scheduled_task_id)
        return dict.fromkeys(catalog_policies, current_policy)

    monkeypatch.setattr(gate, "resolve_action_policies", resolve)
    addon = _build(
        resolver=StubResolver(
            sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
        ),
        matcher=_StubMatcher(result=_MATCH),
    )
    spy = _spy_pipeline(addon, monkeypatch)
    first = make_flow(proxy_auth=_basic_auth(_TAG_UUID))
    await addon.request(first)
    assert first.response is None
    assert len(spy.dispatched) == 1
    assert not spy.approval_ran

    current_policy = ActionPolicy.DENY
    second = make_flow(proxy_auth=_basic_auth(_TAG_UUID))
    await addon.request(second)
    _assert_403(second, SandboxProxyError.POLICY_DENIED)
    assert len(spy.dispatched) == 1
    assert owners == [task_id, task_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["disable", "run_finished", "recognition_failed"])
async def test_approval_cannot_bypass_changes_during_wait(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    task_id = uuid4()
    active: tuple[UUID, UUID] | None = (_RUN_ID, task_id)
    current_policy = ActionPolicy.ASK
    monkeypatch.setattr(
        gate, "get_active_scheduled_task_context", lambda _db, _session: active
    )
    monkeypatch.setattr(
        gate,
        "resolve_action_policies",
        lambda _db, *, catalog_policies, **_kwargs: dict.fromkeys(
            catalog_policies, current_policy
        ),
    )
    matcher = _StubMatcher(result=_MATCH)
    addon = _build(
        resolver=StubResolver(
            sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
        ),
        matcher=matcher,
    )
    spy = _spy_pipeline(addon, monkeypatch)

    async def decide(*_args: object) -> ApprovalDecision:
        nonlocal active, current_policy
        if change == "disable":
            current_policy = ActionPolicy.DENY
        elif change == "run_finished":
            active = None
            current_policy = ActionPolicy.ALWAYS
        else:
            matcher._exc = RuntimeError("registry unavailable")
        return ApprovalDecision.APPROVED

    monkeypatch.setattr(addon, "_await_decision", decide)
    monkeypatch.setattr(
        addon, "_terminalize_after_unhandled_error", lambda *_args: None
    )
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))
    await addon.request(flow)
    assert spy.dispatched == []
    expected = {
        "disable": SandboxProxyError.POLICY_DENIED,
        "run_finished": SandboxProxyError.NO_ACTIVE_SESSION,
        "recognition_failed": SandboxProxyError.INTERNAL_ERROR,
    }
    _assert_403(flow, expected[change])


@pytest.mark.asyncio
async def test_policy_read_failure_does_not_fall_back_to_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> dict[str, ActionPolicy]:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(gate, "resolve_action_policies", fail)
    addon = _build(
        resolver=StubResolver(
            sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
        ),
        matcher=_StubMatcher(result=_MATCH_ALWAYS),
    )
    spy = _spy_pipeline(addon, monkeypatch)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))
    await addon.request(flow)
    _assert_403(flow, SandboxProxyError.INTERNAL_ERROR)
    assert spy.dispatched == []
    assert not spy.approval_ran


@pytest.mark.asyncio
async def test_disabled_action_cannot_use_session_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _SessionGrantCache(granted=True)
    monkeypatch.setattr(
        gate,
        "resolve_action_policies",
        lambda _db, *, catalog_policies, **_kwargs: dict.fromkeys(
            catalog_policies, ActionPolicy.DENY
        ),
    )
    addon = _build(
        resolver=StubResolver(
            sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
        ),
        matcher=_StubMatcher(result=_MATCH),
        cache_factory=lambda _tenant: cache,
    )
    spy = _spy_pipeline(addon, monkeypatch)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))
    await addon.request(flow)
    _assert_403(flow, SandboxProxyError.POLICY_DENIED)
    assert cache.get_calls == []
    assert spy.dispatched == []


@pytest.mark.asyncio
async def test_policy_recheck_uses_catalog_defaults_not_previous_effective_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults_seen: list[dict[str, ActionPolicy]] = []

    def resolve(
        _db: Session,
        *,
        catalog_policies: dict[str, ActionPolicy],
        **_kwargs: object,
    ) -> dict[str, ActionPolicy]:
        defaults_seen.append(dict(catalog_policies))
        # An explicit personal Ask is reset while the request waits for approval.
        return {
            action: ActionPolicy.ASK if len(defaults_seen) == 1 else default
            for action, default in catalog_policies.items()
        }

    monkeypatch.setattr(gate, "resolve_action_policies", resolve)
    addon = _build(
        resolver=StubResolver(
            sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
        ),
        matcher=_StubMatcher(result=_MATCH_ALWAYS),
    )
    spy = _spy_pipeline(addon, monkeypatch, decision=ApprovalDecision.APPROVED)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))
    await addon.request(flow)
    assert defaults_seen == [{"slack.channels.read": ActionPolicy.ALWAYS}] * 2
    assert len(spy.dispatched) == 1
    assert flow.response is None


@pytest.mark.asyncio
async def test_newly_ask_action_is_not_covered_by_old_session_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_action, second_action = _MATCH_MULTI_ASK.actions
    resolutions = 0

    def resolve(
        _db: Session,
        *,
        catalog_policies: dict[str, ActionPolicy],
        **_kwargs: object,
    ) -> dict[str, ActionPolicy]:
        nonlocal resolutions
        resolutions += 1
        return {
            action: ActionPolicy.ALWAYS
            if resolutions == 1 and action == second_action.action_type
            else ActionPolicy.ASK
            for action in catalog_policies
        }

    monkeypatch.setattr(gate, "resolve_action_policies", resolve)
    cache = _SessionGrantCache(granted_action_types={first_action.action_type})
    addon = _build(
        resolver=StubResolver(
            sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
        ),
        matcher=_StubMatcher(result=_MATCH_MULTI_ASK),
        cache_factory=lambda _tenant: cache,
    )
    spy = _spy_pipeline(addon, monkeypatch)
    _spy_approval_insert(monkeypatch)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))
    await addon.request(flow)
    _assert_403(flow, SandboxProxyError.NOT_AUTHORIZED)
    assert spy.dispatched == []
    assert not spy.approval_ran


@pytest.mark.asyncio
async def test_unknown_external_action_ignores_historical_session_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _SessionGrantCache(granted=True)
    addon = _build(
        resolver=StubResolver(
            sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
        ),
        matcher=_StubMatcher(
            result=make_matched_actions(
                action_type="unspecified", policy=ActionPolicy.ASK
            )
        ),
        cache_factory=lambda _tenant: cache,
    )
    spy = _spy_pipeline(addon, monkeypatch, decision=ApprovalDecision.REJECTED)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))
    await addon.request(flow)
    assert spy.approval_ran
    assert spy.dispatched == []
    assert cache.get_calls == []
    _assert_403(flow, SandboxProxyError.USER_REJECTED)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_mcp_protocol_checks_task_app_without_requesting_approval(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    monkeypatch.setattr(
        gate, "get_active_scheduled_task_context", lambda *_args: (_RUN_ID, uuid4())
    )
    monkeypatch.setattr(gate, "task_app_enabled", lambda *_args: enabled)
    addon = _build(
        resolver=StubResolver(
            sandbox=make_resolved_sandbox(), session_by_id=UUID(_TAG_UUID)
        ),
        matcher=_StubMatcher(result=McpProtocolRequest(target=_MATCH_MCP.target)),
    )
    spy = _spy_pipeline(addon, monkeypatch)
    flow = make_flow(proxy_auth=_basic_auth(_TAG_UUID))
    await addon.request(flow)
    assert not spy.approval_ran
    assert bool(spy.dispatched) is enabled
    if enabled:
        assert flow.response is None
    else:
        _assert_403(flow, SandboxProxyError.POLICY_DENIED)


@pytest.mark.asyncio
async def test_mcp_protocol_without_session_is_blocked() -> None:
    addon = _build(
        resolver=StubResolver(sandbox=make_resolved_sandbox()),
        matcher=_StubMatcher(result=McpProtocolRequest(target=_MATCH_MCP.target)),
    )
    flow = make_flow()
    await addon.request(flow)
    _assert_403(flow, SandboxProxyError.NO_ACTIVE_SESSION)
