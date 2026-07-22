"""Unit tests for `CredentialInjectionDispatcher`.

The dispatcher is the single seam between the gate and any concrete
`CredentialResolver`; per-resolver behaviour is tested separately.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from onyx.external_apps.matching.engine import AllMatchedActions
from onyx.sandbox_proxy.credential_injection import (
    CredentialInjectionDispatcher,
    CredentialResolver,
    CredentialUnavailableError,
    InjectionContext,
    InjectionOutcome,
)
from tests.unit.sandbox_proxy.conftest import (
    RecordingCredentialResolver,
    make_flow,
    make_matched_actions,
    make_resolved_sandbox,
)


def _ctx(*, matched_actions: AllMatchedActions | None = None) -> InjectionContext:
    return InjectionContext(
        sandbox=make_resolved_sandbox(), matched_actions=matched_actions
    )


def test_no_resolver_claims_returns_pass_through() -> None:
    a = RecordingCredentialResolver(claims_result=False)
    b = RecordingCredentialResolver(claims_result=False)
    flow = make_flow()
    flow.request.headers["X-Existing"] = "preserve"

    result = CredentialInjectionDispatcher([a, b]).apply(flow, _ctx())

    assert result.outcome is InjectionOutcome.PASS_THROUGH
    assert flow.request.headers["X-Existing"] == "preserve"
    assert a.claims_calls and b.claims_calls
    assert a.resolve_calls == [] and b.resolve_calls == []


def test_first_claim_wins() -> None:
    """Registered order is priority order; later resolvers are not queried."""
    first = RecordingCredentialResolver(
        claims_result=True, headers={"Authorization": "from-first"}
    )
    second = RecordingCredentialResolver(
        claims_result=True, headers={"Authorization": "from-second"}
    )
    flow = make_flow()

    CredentialInjectionDispatcher([first, second]).apply(flow, _ctx())

    assert flow.request.headers["Authorization"] == "from-first"
    assert first.resolve_calls != []
    assert second.resolve_calls == []
    assert second.claims_calls == []


def test_injected_headers_overwrite_existing() -> None:
    """Pod ships placeholders; the dispatcher overwrites them set/replace."""
    resolver = RecordingCredentialResolver(
        claims_result=True, headers={"Authorization": "Bearer real"}
    )
    flow = make_flow()
    flow.request.headers["Authorization"] = "placeholder"

    CredentialInjectionDispatcher([resolver]).apply(flow, _ctx())

    assert flow.request.headers["Authorization"] == "Bearer real"


def test_resolver_claiming_but_returning_no_headers_is_claimed() -> None:
    """A resolver can claim a request without writing any headers."""
    resolver = RecordingCredentialResolver(claims_result=True, headers={})

    result = CredentialInjectionDispatcher([resolver]).apply(make_flow(), _ctx())

    assert result.outcome is InjectionOutcome.CLAIMED


def test_credential_unavailable_returns_blocked() -> None:
    resolver = RecordingCredentialResolver(
        claims_result=True, exc=CredentialUnavailableError("no PAT for sandbox")
    )
    flow = make_flow()

    result = CredentialInjectionDispatcher([resolver]).apply(flow, _ctx())

    assert result.outcome is InjectionOutcome.BLOCKED
    assert result.block_detail is None
    assert "Authorization" not in flow.request.headers


def test_credential_unavailable_sandbox_detail_reaches_result() -> None:
    """Agent-facing prose on the error surfaces as the result's block_detail."""
    resolver = RecordingCredentialResolver(
        claims_result=True,
        exc=CredentialUnavailableError(
            "internal: no config row 42",
            sandbox_detail="Connect the GitHub MCP server, then retry.",
        ),
    )

    result = CredentialInjectionDispatcher([resolver]).apply(make_flow(), _ctx())

    assert result.outcome is InjectionOutcome.BLOCKED
    assert result.block_detail == "Connect the GitHub MCP server, then retry."


def test_unexpected_exception_returns_blocked() -> None:
    """Non-CredentialUnavailable resolver errors also fail closed."""
    resolver = RecordingCredentialResolver(
        claims_result=True, exc=RuntimeError("db down mid-resolve")
    )

    result = CredentialInjectionDispatcher([resolver]).apply(make_flow(), _ctx())

    assert result.outcome is InjectionOutcome.BLOCKED


def test_claims_exception_falls_through_to_next_resolver() -> None:
    """A buggy `claims` predicate must not deny later resolvers a chance."""
    bad = MagicMock(spec=CredentialResolver)
    bad.claims.side_effect = RuntimeError("claims is buggy")
    good = RecordingCredentialResolver(claims_result=True, headers={"X-Hdr": "val"})
    flow = make_flow()

    result = CredentialInjectionDispatcher([bad, good]).apply(flow, _ctx())

    assert result.outcome is InjectionOutcome.INJECTED
    assert flow.request.headers["X-Hdr"] == "val"


def test_all_claims_raise_returns_pass_through() -> None:
    """No usable resolver: fail OPEN — the dispatcher itself never blocks."""
    a = MagicMock(spec=CredentialResolver)
    a.claims.side_effect = RuntimeError("a")
    b = MagicMock(spec=CredentialResolver)
    b.claims.side_effect = RuntimeError("b")

    result = CredentialInjectionDispatcher([a, b]).apply(make_flow(), _ctx())

    assert result.outcome is InjectionOutcome.PASS_THROUGH


def test_resolver_receives_request_and_full_context() -> None:
    """Sanity: `claims` and `resolve` both see the same request + ctx the
    dispatcher was handed, unchanged."""
    sandbox = make_resolved_sandbox(tenant_id="tenant-xyz")
    matched_actions = make_matched_actions()
    resolver = RecordingCredentialResolver(claims_result=True)
    flow = make_flow(host="api.anthropic.com")
    ctx = InjectionContext(sandbox=sandbox, matched_actions=matched_actions)

    CredentialInjectionDispatcher([resolver]).apply(flow, ctx)

    [(claim_request, claim_ctx)] = resolver.claims_calls
    assert claim_request is flow.request
    assert claim_ctx is ctx
    assert resolver.resolve_calls == [ctx]
