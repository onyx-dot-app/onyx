"""Unit tests for `CredentialInjectionDispatcher`.

The dispatcher is the single seam between the gate and any concrete
`CredentialResolver`; per-resolver behaviour is tested separately.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.credential_injection import CredentialResolver
from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.credential_injection import InjectionOutcome
from tests.unit.sandbox_proxy.conftest import make_action_match
from tests.unit.sandbox_proxy.conftest import make_flow as _flow
from tests.unit.sandbox_proxy.conftest import make_resolved_sandbox as _sandbox
from tests.unit.sandbox_proxy.conftest import noop_db_factory
from tests.unit.sandbox_proxy.conftest import RecordingCredentialResolver


def _ctx(*, match=None) -> InjectionContext:  # type: ignore[no-untyped-def]
    return InjectionContext(
        sandbox=_sandbox(), match=match, db_session_factory=noop_db_factory
    )


def test_no_resolver_claims_returns_pass_through() -> None:
    a = RecordingCredentialResolver(claims_result=False)
    b = RecordingCredentialResolver(claims_result=False)
    dispatcher = CredentialInjectionDispatcher([a, b])
    flow = _flow()
    flow.request.headers["X-Existing"] = "preserve"

    outcome = dispatcher.apply(flow, _ctx())

    assert outcome is InjectionOutcome.PASS_THROUGH
    assert flow.request.headers["X-Existing"] == "preserve"
    assert a.claims_calls and b.claims_calls
    assert a.resolve_calls == [] and b.resolve_calls == []


def test_first_claim_wins() -> None:
    """Registered order is priority order; later resolvers are not even queried."""
    first = RecordingCredentialResolver(
        claims_result=True, headers={"Authorization": "from-first"}
    )
    second = RecordingCredentialResolver(
        claims_result=True, headers={"Authorization": "from-second"}
    )
    dispatcher = CredentialInjectionDispatcher([first, second])
    flow = _flow()

    outcome = dispatcher.apply(flow, _ctx())

    assert outcome is InjectionOutcome.INJECTED
    assert flow.request.headers["Authorization"] == "from-first"
    assert first.resolve_calls != []
    assert second.resolve_calls == []
    assert second.claims_calls == []


def test_injected_headers_overwrite_existing() -> None:
    """Pod ships placeholders; the dispatcher overwrites them set/replace."""
    resolver = RecordingCredentialResolver(
        claims_result=True, headers={"Authorization": "Bearer real"}
    )
    dispatcher = CredentialInjectionDispatcher([resolver])
    flow = _flow()
    flow.request.headers["Authorization"] = "placeholder"

    dispatcher.apply(flow, _ctx())

    assert flow.request.headers["Authorization"] == "Bearer real"


def test_resolver_claiming_but_returning_no_headers_is_injected() -> None:
    """The claim is the contract — empty header set is INJECTED, not PASS_THROUGH."""
    resolver = RecordingCredentialResolver(claims_result=True, headers={})
    dispatcher = CredentialInjectionDispatcher([resolver])

    outcome = dispatcher.apply(_flow(), _ctx())

    assert outcome is InjectionOutcome.INJECTED


def test_credential_unavailable_returns_blocked() -> None:
    resolver = RecordingCredentialResolver(
        claims_result=True, exc=CredentialUnavailableError("no PAT for sandbox")
    )
    dispatcher = CredentialInjectionDispatcher([resolver])
    flow = _flow()

    outcome = dispatcher.apply(flow, _ctx())

    assert outcome is InjectionOutcome.BLOCKED
    assert "Authorization" not in flow.request.headers


def test_unexpected_exception_returns_blocked() -> None:
    """Any non-Credential-Unavailable resolver error is also fail-closed."""
    resolver = RecordingCredentialResolver(
        claims_result=True, exc=RuntimeError("db down mid-resolve")
    )
    dispatcher = CredentialInjectionDispatcher([resolver])

    outcome = dispatcher.apply(_flow(), _ctx())

    assert outcome is InjectionOutcome.BLOCKED


def test_claims_exception_falls_through_to_next_resolver() -> None:
    """A buggy `claims` predicate must not deny later resolvers a chance."""
    bad = MagicMock(spec=CredentialResolver)
    bad.claims.side_effect = RuntimeError("claims is buggy")
    good = RecordingCredentialResolver(claims_result=True, headers={"X-Hdr": "val"})
    dispatcher = CredentialInjectionDispatcher([bad, good])
    flow = _flow()

    outcome = dispatcher.apply(flow, _ctx())

    assert outcome is InjectionOutcome.INJECTED
    assert flow.request.headers["X-Hdr"] == "val"


def test_all_claims_raise_returns_pass_through() -> None:
    """No usable resolver: fail OPEN — the dispatcher itself never blocks."""
    a = MagicMock(spec=CredentialResolver)
    a.claims.side_effect = RuntimeError("a")
    b = MagicMock(spec=CredentialResolver)
    b.claims.side_effect = RuntimeError("b")

    outcome = CredentialInjectionDispatcher([a, b]).apply(_flow(), _ctx())

    assert outcome is InjectionOutcome.PASS_THROUGH


def test_dispatcher_passes_full_context_to_resolver() -> None:
    """The `InjectionContext` reaches `resolve()` unchanged (sandbox, match,
    db_session_factory all forwarded), and `claims()` sees the host + ctx."""
    sandbox = _sandbox(tenant_id="tenant-xyz", user_id=uuid4())
    match = make_action_match()
    resolver = RecordingCredentialResolver(claims_result=True)
    dispatcher = CredentialInjectionDispatcher([resolver])
    flow = _flow(host="api.anthropic.com")
    ctx = InjectionContext(
        sandbox=sandbox, match=match, db_session_factory=noop_db_factory
    )

    dispatcher.apply(flow, ctx)

    assert resolver.claims_calls == [("api.anthropic.com", ctx)]
    assert resolver.resolve_calls == [ctx]
    seen = resolver.resolve_calls[0]
    assert seen.sandbox is sandbox
    assert seen.match is match
    assert seen.db_session_factory is noop_db_factory
