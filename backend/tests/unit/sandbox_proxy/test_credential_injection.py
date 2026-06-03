"""Unit tests for `CredentialInjectionDispatcher`.

The dispatcher is the single seam between the gate and any concrete
`CredentialResolver`; per-resolver behaviour is tested separately.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from onyx.external_apps.matching.engine import RequestMatch
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.credential_injection import CredentialResolver
from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.credential_injection import InjectionOutcome
from onyx.sandbox_proxy.errors import SandboxProxyError
from tests.unit.sandbox_proxy.conftest import make_flow as _flow
from tests.unit.sandbox_proxy.conftest import make_request_match
from tests.unit.sandbox_proxy.conftest import make_resolved_sandbox as _sandbox
from tests.unit.sandbox_proxy.conftest import RecordingCredentialResolver


def _ctx(*, match: RequestMatch | None = None) -> InjectionContext:
    return InjectionContext(sandbox=_sandbox(), match=match)


def test_no_resolver_claims_returns_pass_through() -> None:
    a = RecordingCredentialResolver(claims_result=False)
    b = RecordingCredentialResolver(claims_result=False)
    flow = _flow()
    flow.request.headers["X-Existing"] = "preserve"

    outcome = CredentialInjectionDispatcher([a, b]).apply(flow, _ctx())

    assert outcome is InjectionOutcome.PASS_THROUGH
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
    flow = _flow()

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
    flow = _flow()
    flow.request.headers["Authorization"] = "placeholder"

    CredentialInjectionDispatcher([resolver]).apply(flow, _ctx())

    assert flow.request.headers["Authorization"] == "Bearer real"


def test_resolver_claiming_but_returning_no_headers_is_injected() -> None:
    """Claim is the contract — empty header set is INJECTED, not PASS_THROUGH."""
    resolver = RecordingCredentialResolver(claims_result=True, headers={})

    outcome = CredentialInjectionDispatcher([resolver]).apply(_flow(), _ctx())

    assert outcome is InjectionOutcome.INJECTED


def test_credential_unavailable_returns_blocked() -> None:
    resolver = RecordingCredentialResolver(
        claims_result=True, exc=CredentialUnavailableError("no PAT for sandbox")
    )
    flow = _flow()

    outcome = CredentialInjectionDispatcher([resolver]).apply(flow, _ctx())

    assert outcome is InjectionOutcome.BLOCKED
    assert "Authorization" not in flow.request.headers


def test_unexpected_exception_returns_blocked() -> None:
    """Non-CredentialUnavailable resolver errors also fail closed."""
    resolver = RecordingCredentialResolver(
        claims_result=True, exc=RuntimeError("db down mid-resolve")
    )

    outcome = CredentialInjectionDispatcher([resolver]).apply(_flow(), _ctx())

    assert outcome is InjectionOutcome.BLOCKED


def test_claims_exception_falls_through_to_next_resolver() -> None:
    """A buggy `claims` predicate must not deny later resolvers a chance."""
    bad = MagicMock(spec=CredentialResolver)
    bad.claims.side_effect = RuntimeError("claims is buggy")
    good = RecordingCredentialResolver(claims_result=True, headers={"X-Hdr": "val"})
    flow = _flow()

    outcome = CredentialInjectionDispatcher([bad, good]).apply(flow, _ctx())

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


def test_apply_or_block_writes_403_on_blocked() -> None:
    """The high-level seam: BLOCKED → sandbox-visible 403 with the documented body."""
    resolver = RecordingCredentialResolver(
        claims_result=True, exc=CredentialUnavailableError("no creds")
    )
    flow = _flow()

    CredentialInjectionDispatcher([resolver]).apply_or_block(flow, _ctx())

    assert flow.response is not None
    assert flow.response.status_code == 403
    content = flow.response.content
    assert content is not None
    body = json.loads(content)
    assert body["error"] == SandboxProxyError.CREDENTIAL_ERROR.value
    assert body["message"]


def test_apply_or_block_leaves_response_unset_on_inject_or_pass_through() -> None:
    """INJECTED and PASS_THROUGH both leave `flow.response` untouched so the
    request forwards through mitmproxy."""
    claiming = RecordingCredentialResolver(claims_result=True, headers={"X": "y"})
    not_claiming = RecordingCredentialResolver(claims_result=False)

    flow_a = _flow()
    CredentialInjectionDispatcher([claiming]).apply_or_block(flow_a, _ctx())
    assert flow_a.response is None

    flow_b = _flow()
    CredentialInjectionDispatcher([not_claiming]).apply_or_block(flow_b, _ctx())
    assert flow_b.response is None


def test_resolver_receives_request_and_full_context() -> None:
    """Sanity: `claims` and `resolve` both see the same request + ctx the
    dispatcher was handed, unchanged."""
    sandbox = _sandbox(tenant_id="tenant-xyz")
    match = make_request_match()
    resolver = RecordingCredentialResolver(claims_result=True)
    flow = _flow(host="api.anthropic.com")
    ctx = InjectionContext(sandbox=sandbox, match=match)

    CredentialInjectionDispatcher([resolver]).apply(flow, ctx)

    [(claim_request, claim_ctx)] = resolver.claims_calls
    assert claim_request is flow.request
    assert claim_ctx is ctx
    assert resolver.resolve_calls == [ctx]
