"""Operator URL exceptions keep destination and request checks separate."""

import ipaddress
import json
from unittest.mock import MagicMock

import pytest
from mitmproxy import connection, http
from mitmproxy.proxy import server_hooks

from onyx.db.enums import EndpointPolicy
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.destination_policy import (
    parse_destination_policy,
    resolve_destination,
)
from onyx.sandbox_proxy.errors import SandboxProxyError
from onyx.sandbox_proxy.resolvers.mcp_matching import CraftMCPTarget
from onyx.sandbox_proxy.resolvers.mcp_server import MCPServerResolver
from tests.unit.sandbox_proxy.conftest import (
    NoMatchedRequest,
    RecordingCredentialResolver,
    StubResolver,
    make_flow,
    make_matched_actions,
    make_resolved_sandbox,
    unused_cache,
)
from tests.unit.sandbox_proxy.test_destination_policy import mock_destination_dns


@pytest.mark.parametrize(
    "url",
    [
        "",
        "mcp.internal:8000",
        "ftp://mcp.internal",
        "http://*.internal",
        "http://user:password@mcp.internal",
        "http://@mcp.internal",
        "http://mcp.internal/mcp",
        "http://mcp.internal?",
        "http://mcp.internal#",
        "http://mcp.internal:0",
        "http://mcp.internal:65536",
        "http://mcp.internal:",
        "http://mcp.internal:invalid",
        "http://mcp.\ninternal",
        "http://mcp%2einternal",
        "http://127.0.0.1",
        "http://169.254.169.254",
        "http://[::1]",
        "http://[::]",
        "http://[fd00::1]suffix",
        "http://[fe80::1%25eth0]",
    ],
)
def test_invalid_origin_is_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="ALLOWED_INTERNAL_URLS entry 1"):
        parse_destination_policy("", allowed_internal_urls=[url])


@pytest.mark.parametrize("scheme,port", [("http", 80), ("https", 443), ("https", 8443)])
def test_origin_matches_exactly(
    monkeypatch: pytest.MonkeyPatch, scheme: str, port: int
) -> None:
    mock_destination_dns(monkeypatch, ["10.1.2.3", "fd00::1234"])
    policy = parse_destination_policy(
        "", allowed_internal_urls=[f" {scheme}://SERVICE.EXAMPLE:{port}/ "]
    )
    assert resolve_destination(policy, "service.example", port, scheme=scheme) == (
        "10.1.2.3",
        "fd00::1234",
    )
    assert (
        resolve_destination(policy, "service.example", port + 1, scheme=scheme) is None
    )
    assert (
        resolve_destination(
            policy,
            "service.example",
            port,
            scheme="https" if scheme == "http" else "http",
        )
        is None
    )
    assert resolve_destination(policy, "service.example", port) is None
    assert resolve_destination(policy, "10.1.2.3", port, scheme=scheme) is None
    mock_destination_dns(monkeypatch, ["10.1.2.3"], expected_host="alias.example")
    assert resolve_destination(policy, "alias.example", port, scheme=scheme) is None


@pytest.mark.parametrize(
    "address,allowed",
    [
        ("10.1.2.3", True),
        ("100.64.0.1", True),
        ("fd00::1234", True),
        ("::ffff:10.1.2.3", True),
        ("64:ff9b::a01:203", True),
        ("127.0.0.1", False),
        ("::1", False),
        ("0.0.0.0", False),
        ("::", False),
        ("169.254.169.254", False),
        ("fd00:ec2::254", False),
        ("fe80::1", False),
        ("::ffff:127.0.0.1", False),
        ("64:ff9b::a9fe:a9fe", False),
    ],
)
@pytest.mark.parametrize("reused_connection", [False, True])
def test_allowed_origin_checks_all_addresses(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
    allowed: bool,
    reused_connection: bool,
) -> None:
    addresses = ["8.8.8.8", address]
    mock_destination_dns(monkeypatch, addresses)
    policy = parse_destination_policy(
        "", allowed_internal_urls=["https://service.example"]
    )
    result = resolve_destination(
        policy,
        "service.example",
        443,
        scheme="https",
        upstream_addresses=tuple(addresses) if reused_connection else (),
    )
    expected = tuple(str(ipaddress.ip_address(ip)) for ip in addresses)
    assert result == (expected if allowed else None)


def test_allowlist_overrides_internal_cidrs(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_destination_dns(monkeypatch, ["2600:ffff::1"])
    policy = parse_destination_policy(
        "", ["2600:ffff::/32"], ["https://service.example"]
    )
    assert resolve_destination(policy, "service.example", 443, scheme="https") == (
        "2600:ffff::1",
    )
    assert resolve_destination(policy, "2600:ffff::1", 443, scheme="https") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("allowlisted", [False, True])
@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("path", ["/health", "/api/reports?format=json"])
async def test_allowlist_permits_generic_internal_requests_without_mcp(
    monkeypatch: pytest.MonkeyPatch, allowlisted: bool, scheme: str, path: str
) -> None:
    mock_destination_dns(monkeypatch, ["10.1.2.3"])
    origin = f"{scheme}://service.example:8000"
    sandbox = make_resolved_sandbox()
    identity = StubResolver(sandbox=sandbox)
    resolver = MCPServerResolver()
    targets = MagicMock(return_value=())
    access = MagicMock(return_value=frozenset())
    monkeypatch.setattr(resolver, "_load_targets", targets)
    monkeypatch.setattr(resolver, "_load_accessible_ids", access)
    settings = MagicMock(
        side_effect=AssertionError("Allowlist needs no tenant settings")
    )
    monkeypatch.setattr(
        "onyx.sandbox_proxy.destination_policy.get_security_settings", settings
    )
    addon = GateAddon(
        identity=identity,
        request_evaluator=NoMatchedRequest(),
        cache_factory=unused_cache,
        proxy_instance_id="test",
        credential_dispatcher=CredentialInjectionDispatcher([resolver]),
        destination_policy=parse_destination_policy(
            "", allowed_internal_urls=[origin] if allowlisted else []
        ),
        mcp_resolver=resolver,
    )
    flow = make_flow()
    flow.request = http.Request.make("GET", f"{origin}{path}")

    await addon.request(flow)

    if allowlisted:
        assert flow.response is None
        assert flow.request.url == f"{origin}{path}"
        assert "Authorization" not in flow.request.headers
        access.assert_not_called()
    else:
        assert flow.response is not None and flow.response.status_code == 403
        body = flow.response.get_text()
        assert body is not None
        assert json.loads(body)["error"] == SandboxProxyError.DESTINATION_BLOCKED.value
    targets.assert_called_once_with(sandbox.tenant_id)
    settings.assert_not_called()
    assert not identity.resolve_session_by_id_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_allowlist_does_not_grant_access_to_registered_mcp(
    monkeypatch: pytest.MonkeyPatch, scheme: str
) -> None:
    sandbox = make_resolved_sandbox()
    resolver = MCPServerResolver()
    targets = MagicMock(
        return_value=(
            CraftMCPTarget(
                server_id=1,
                scheme=scheme,
                host="10.1.2.3",
                port=8000,
                path_prefix="/mcp",
            ),
        )
    )
    access = MagicMock(return_value=frozenset())
    monkeypatch.setattr(resolver, "_load_targets", targets)
    monkeypatch.setattr(resolver, "_load_accessible_ids", access)
    origin = f"{scheme}://10.1.2.3:8000"
    addon = GateAddon(
        identity=StubResolver(sandbox=sandbox),
        request_evaluator=NoMatchedRequest(),
        cache_factory=unused_cache,
        proxy_instance_id="test",
        credential_dispatcher=CredentialInjectionDispatcher([resolver]),
        destination_policy=parse_destination_policy("", allowed_internal_urls=[origin]),
        mcp_resolver=resolver,
    )
    flow = make_flow()
    # Plumbing reaches the resolver's access check without an action-policy denial.
    flow.request = http.Request.make(
        "POST",
        f"{origin}/mcp",
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
        {"Content-Type": "application/json"},
    )

    await addon.request(flow)

    assert flow.response is not None and flow.response.status_code == 403
    body = flow.response.get_text()
    assert body is not None
    assert json.loads(body)["error"] == SandboxProxyError.CREDENTIAL_ERROR.value
    assert "Authorization" not in flow.request.headers
    targets.assert_called_once_with(sandbox.tenant_id)
    access.assert_called_once_with(sandbox.tenant_id, sandbox.user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["request", "connect", "server_connect"])
@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_proxy_hooks_accept_configured_origin(
    monkeypatch: pytest.MonkeyPatch, phase: str, scheme: str
) -> None:
    # CONNECT carries HTTPS; an HTTP-only exception must not open that tunnel.
    host, port = "10.1.2.3", 8000
    pin = MagicMock()
    monkeypatch.setattr("onyx.sandbox_proxy.addons.gate.pin_destination", pin)
    addon = GateAddon(
        identity=StubResolver(sandbox=make_resolved_sandbox()),
        request_evaluator=NoMatchedRequest(),
        cache_factory=unused_cache,
        proxy_instance_id="test",
        credential_dispatcher=CredentialInjectionDispatcher([]),
        destination_policy=parse_destination_policy(
            "", allowed_internal_urls=[f"{scheme}://{host}:{port}"]
        ),
    )
    flow = make_flow(host=host, port=port)
    flow.request.scheme = scheme
    if phase == "server_connect":
        upstream = connection.Server(address=(host, port), tls=scheme == "https")
        await addon.server_connect(
            server_hooks.ServerConnectionHookData(
                server=upstream, client=flow.client_conn
            )
        )
        assert upstream.error is None
        pin.assert_called_once_with(host, port, (host,))
    else:
        if phase == "connect":
            await addon.http_connect(flow)
        else:
            await addon.request(flow)
        assert (flow.response is None) == (phase != "connect" or scheme == "https")


@pytest.mark.asyncio
@pytest.mark.parametrize("known_sandbox", [False, True])
async def test_allowlist_keeps_identity_and_action_checks(known_sandbox: bool) -> None:
    evaluator = MagicMock()
    evaluator.evaluate.return_value = make_matched_actions(policy=EndpointPolicy.DENY)
    credential = RecordingCredentialResolver(headers={"Authorization": "secret"})
    addon = GateAddon(
        identity=StubResolver(
            sandbox=make_resolved_sandbox() if known_sandbox else None
        ),
        request_evaluator=evaluator,
        cache_factory=unused_cache,
        proxy_instance_id="test",
        credential_dispatcher=CredentialInjectionDispatcher([credential]),
        destination_policy=parse_destination_policy(
            "", allowed_internal_urls=["http://10.1.2.3:8000"]
        ),
    )
    flow = make_flow(host="10.1.2.3", port=8000)
    flow.request.scheme = "http"
    await addon.request(flow)
    assert flow.response is not None and flow.response.status_code == 403
    assert not credential.resolve_calls
    assert evaluator.evaluate.call_count == int(known_sandbox)
