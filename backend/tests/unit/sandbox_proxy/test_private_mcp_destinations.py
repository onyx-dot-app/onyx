"""Private MCP origins stay scoped to the sandbox user and exact origin."""

from unittest.mock import MagicMock

import pytest
from mitmproxy import connection
from mitmproxy.proxy import server_hooks

from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.destination_policy import parse_destination_policy
from onyx.sandbox_proxy.resolvers.mcp_matching import CraftMCPTarget
from onyx.sandbox_proxy.resolvers.mcp_server import MCPServerResolver
from tests.unit.sandbox_proxy.conftest import (
    NoMatchedRequest,
    StubResolver,
    make_flow,
    make_resolved_sandbox,
    unused_cache,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase",
    ["request", "connect", "server_connect", "request_http", "server_connect_http"],
)
@pytest.mark.parametrize("host", ["10.1.2.3", "fd00::1234"])
@pytest.mark.parametrize(
    "case",
    [
        "allowed",
        "wrong_scheme",
        "wrong_port",
        "wrong_host",
        "disabled",
        "inaccessible",
        "unknown",
        "db_error",
    ],
)
async def test_private_mcp_origin(
    monkeypatch: pytest.MonkeyPatch, phase: str, host: str, case: str
) -> None:
    scheme = "http" if phase.endswith("_http") else "https"
    sandbox = make_resolved_sandbox()
    resolver = MCPServerResolver()
    targets = (
        ()
        if case == "disabled"
        else (
            CraftMCPTarget(
                server_id=1,
                scheme=("https" if scheme == "http" else "http")
                if case == "wrong_scheme"
                else scheme,
                host="10.9.9.9" if case == "wrong_host" else host,
                port=8444 if case == "wrong_port" else 8443,
                path_prefix="/mcp",
            ),
        )
    )
    load_targets = MagicMock(return_value=targets)
    load_access = MagicMock(
        return_value=frozenset() if case == "inaccessible" else frozenset({1})
    )
    if case == "db_error":
        load_access.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(resolver, "_load_targets", load_targets)
    monkeypatch.setattr(resolver, "_load_accessible_ids", load_access)
    pin = MagicMock()
    monkeypatch.setattr("onyx.sandbox_proxy.addons.gate.pin_destination", pin)
    addon = GateAddon(
        identity=StubResolver(sandbox=None if case == "unknown" else sandbox),
        request_evaluator=NoMatchedRequest(),
        cache_factory=unused_cache,
        proxy_instance_id="test",
        credential_dispatcher=CredentialInjectionDispatcher([]),
        destination_policy=parse_destination_policy("https://onyx.test"),
        mcp_resolver=resolver,
    )
    flow = make_flow(host=host, port=8443)
    flow.request.scheme = scheme
    if phase.startswith("server_connect"):
        upstream = connection.Server(address=(host, 8443), tls=scheme == "https")
        await addon.server_connect(
            server_hooks.ServerConnectionHookData(
                server=upstream,
                client=connection.Client(
                    peername=("10.0.0.1", 12345), sockname=("127.0.0.1", 8080)
                ),
            )
        )
        assert (upstream.error is None) == (case == "allowed")
        if case == "allowed":
            pin.assert_called_once_with(host, 8443, (host,))
        else:
            pin.assert_not_called()
    else:
        if phase == "connect":
            await addon.http_connect(flow)
        else:
            await addon.request(flow)
        assert (flow.response is None) == (case == "allowed")
    if case != "unknown":
        load_access.assert_called_once_with(sandbox.tenant_id, sandbox.user_id)
