"""Private MCP origins stay scoped to the sandbox user and exact origin."""

from functools import partial
from unittest.mock import MagicMock

import pytest
from mitmproxy import connection
from mitmproxy.proxy import server_hooks

from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.destination_policy import (
    parse_destination_policy,
    resolve_sandbox_destination,
)
from onyx.sandbox_proxy.resolvers.mcp_matching import CraftMCPTarget
from onyx.sandbox_proxy.resolvers.mcp_server import MCPServerResolver
from onyx.server.security.models import SSRFProtectionLevel
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
@pytest.mark.usefixtures("mcp_ssrf_settings")
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


@pytest.mark.parametrize("level", list(SSRFProtectionLevel))
@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize(
    "address,permissive_allowed",
    [
        ("10.1.2.3", True),
        ("fd00::1234", True),
        ("127.0.0.1", False),
        ("::1", False),
        ("169.254.169.254", False),
        ("fd00:ec2::254", False),
        ("fe80::1", False),
        ("::ffff:169.254.169.254", False),
        ("64:ff9b::a9fe:a9fe", False),
        ("64:ff9b::7f00:1", False),
        ("0.0.0.0", False),
        ("::", False),
    ],
)
def test_mcp_validates_resolved_addresses(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
    permissive_allowed: bool,
    level: SSRFProtectionLevel,
    mixed: bool,
) -> None:
    import socket

    from onyx.sandbox_proxy.destination_policy import resolve_destination
    from onyx.server.security.models import outbound_ssrf_params

    dns = MagicMock(
        return_value=[
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, 8443),
            )
        ]
    )
    if mixed:
        dns.return_value.insert(
            0,
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("8.8.8.8", 8443),
            ),
        )
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    result = resolve_destination(
        parse_destination_policy("https://onyx.test"),
        "private-mcp.test",
        8443,
        authorize_internal=lambda: outbound_ssrf_params(level),
    )
    allowed = level in {
        SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK,
        SSRFProtectionLevel.DISABLED,
    } and (
        permissive_allowed
        or (
            level == SSRFProtectionLevel.DISABLED
            and address in {"127.0.0.1", "::1", "64:ff9b::7f00:1"}
        )
    )
    expected = ("8.8.8.8", address) if mixed else (address,)
    assert result == (expected if allowed else None)
    dns.assert_called_once()


def test_mcp_rechecks_tenant_ssrf_settings(
    monkeypatch: pytest.MonkeyPatch, mcp_ssrf_settings: MagicMock
) -> None:
    from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

    sandbox = make_resolved_sandbox(tenant_id="tenant-mcp")
    resolver = MCPServerResolver()
    monkeypatch.setattr(
        resolver,
        "_load_targets",
        lambda _tenant: (
            CraftMCPTarget(
                server_id=1,
                scheme="https",
                host="10.1.2.3",
                port=443,
                path_prefix="/mcp",
            ),
        ),
    )
    monkeypatch.setattr(
        resolver, "_load_accessible_ids", lambda _tenant, _user: frozenset({1})
    )

    def settings(*, allow_fallback: bool = True) -> MagicMock:
        assert not allow_fallback
        assert CURRENT_TENANT_ID_CONTEXTVAR.get() == sandbox.tenant_id
        return mcp_ssrf_settings

    monkeypatch.setattr(
        "onyx.sandbox_proxy.destination_policy.get_security_settings", settings
    )
    resolve = partial(
        resolve_sandbox_destination,
        config=parse_destination_policy("https://onyx.test"),
        resolve_sandbox=StubResolver(sandbox=sandbox).resolve_sandbox,
        mcp_resolver=resolver,
    )
    previous = CURRENT_TENANT_ID_CONTEXTVAR.get()
    for level, expected in [
        (SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK, ("10.1.2.3",)),
        (SSRFProtectionLevel.VALIDATE_LLM, None),
        (SSRFProtectionLevel.DISABLED, ("10.1.2.3",)),
    ]:
        mcp_ssrf_settings.ssrf_protection_level = level
        assert resolve(("10.0.0.1", 1234), "https", "10.1.2.3", 443) == expected
        assert CURRENT_TENANT_ID_CONTEXTVAR.get() == previous
    monkeypatch.setattr(
        "onyx.sandbox_proxy.destination_policy.get_security_settings",
        MagicMock(side_effect=RuntimeError("settings unavailable")),
    )
    assert resolve(("10.0.0.1", 1234), "https", "10.1.2.3", 443) is None
    assert CURRENT_TENANT_ID_CONTEXTVAR.get() == previous


@pytest.mark.parametrize("failure", ["database", "key_value_store"])
def test_private_mcp_denies_real_settings_read_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    from cachetools import TTLCache

    from onyx.server.security import store
    from onyx.server.security.models import SecuritySettingsOverrides
    from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

    sandbox = make_resolved_sandbox(tenant_id="tenant-strict")
    resolver = MCPServerResolver()
    targets = MagicMock(
        return_value=(
            CraftMCPTarget(
                server_id=1,
                scheme="https",
                host="10.1.2.3",
                port=443,
                path_prefix="/mcp",
            ),
        )
    )
    access = MagicMock(return_value=frozenset({1}))
    monkeypatch.setattr(resolver, "_load_targets", targets)
    monkeypatch.setattr(resolver, "_load_accessible_ids", access)
    monkeypatch.setattr(store, "_CACHE", TTLCache(maxsize=100, ttl=10))
    monkeypatch.setattr(store, "MULTI_TENANT", False)
    monkeypatch.setattr(store._cfg, "MCP_SERVER_ALLOW_PRIVATE_NETWORK", True)
    monkeypatch.setattr(store._cfg, "MCP_SERVER_ALLOW_LOOPBACK", False)
    monkeypatch.setattr(store._cfg, "OPEN_URL_VALIDATE_SSRF", True)
    monkeypatch.setattr(store, "get_session_with_current_tenant", MagicMock())
    kv_store = MagicMock()
    monkeypatch.setattr(store, "get_kv_store", lambda: kv_store)
    db_read = MagicMock(
        return_value=SecuritySettingsOverrides(
            ssrf_protection_level=SSRFProtectionLevel.VALIDATE_ALL
        )
    )
    monkeypatch.setattr(store, "_db_load_overrides", db_read)
    resolve = partial(
        resolve_sandbox_destination,
        config=parse_destination_policy("https://onyx.test"),
        resolve_sandbox=StubResolver(sandbox=sandbox).resolve_sandbox,
        mcp_resolver=resolver,
    )

    # Populate MCP access and strict tenant settings through the actual reader.
    assert resolve(("10.0.0.1", 1234), "https", "10.1.2.3", 443) is None
    store.invalidate_security_cache(sandbox.tenant_id)
    if failure == "database":
        db_read.side_effect = RuntimeError("database unavailable")
    else:
        kv_store.load.side_effect = RuntimeError("key-value store unavailable")
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(sandbox.tenant_id)
    try:
        # Auth's legacy reader falls back, but cannot populate the strict cache.
        assert (
            store.get_security_settings().ssrf_protection_level
            == SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK
        )
        assert resolve(("10.0.0.1", 1234), "https", "10.1.2.3", 443) is None
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    targets.assert_called_once()
    access.assert_called_once()
    assert db_read.call_count == 3

    # A successful read with no overrides may use the operator's env settings.
    db_read.side_effect = None
    kv_store.load.side_effect = None
    db_read.return_value = SecuritySettingsOverrides()
    assert resolve(("10.0.0.1", 1234), "https", "10.1.2.3", 443) == ("10.1.2.3",)


@pytest.mark.parametrize(
    "host,allowed",
    [
        ("localhost", False),
        ("127.0.0.1", True),
        ("::1", True),
        ("metadata.google.internal", False),
    ],
)
def test_disabled_ssrf_matches_backend_mcp_hostname_policy(
    monkeypatch: pytest.MonkeyPatch, host: str, allowed: bool
) -> None:
    import socket

    from onyx.sandbox_proxy.destination_policy import resolve_destination
    from onyx.server.features.mcp.ssrf import validate_mcp_outbound_url
    from onyx.server.security.models import outbound_ssrf_params
    from onyx.utils.url import SSRFException

    settings = MagicMock(ssrf_protection_level=SSRFProtectionLevel.DISABLED)
    monkeypatch.setattr(
        "onyx.server.features.mcp.ssrf.get_security_settings", lambda: settings
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        MagicMock(
            return_value=[
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("127.0.0.1", 8000),
                )
            ]
        ),
    )
    authority = f"[{host}]" if ":" in host else host
    url = f"http://{authority}:8000/mcp"
    if allowed:
        assert validate_mcp_outbound_url(url) == url
    else:
        with pytest.raises(SSRFException):
            validate_mcp_outbound_url(url)
    addresses = resolve_destination(
        parse_destination_policy("https://onyx.test"),
        host,
        8000,
        authorize_internal=lambda: outbound_ssrf_params(SSRFProtectionLevel.DISABLED),
    )
    assert (addresses is not None) == allowed


@pytest.mark.parametrize(
    "api_url,addresses,allowed,needs_mcp",
    [
        ("https://onyx.test", ["10.1.2.3"], True, True),
        ("https://onyx.test", ["8.8.8.8", "10.1.2.3"], True, True),
        ("https://onyx.test", ["10.1.2.3", "169.254.169.254"], False, True),
        ("https://onyx.test", ["8.8.8.8"], True, False),
        ("https://private-mcp.test", ["10.1.2.3"], True, False),
        ("https://onyx.test", [], False, False),
    ],
)
@pytest.mark.usefixtures("mcp_ssrf_settings")
def test_destination_resolver_uses_one_dns_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    api_url: str,
    addresses: list[str],
    allowed: bool,
    needs_mcp: bool,
) -> None:
    import socket

    sandbox = make_resolved_sandbox()
    identity = MagicMock(return_value=sandbox)
    mcp = MCPServerResolver()
    access = MagicMock(return_value=True)
    monkeypatch.setattr(mcp, "allows_destination", access)
    # A second resolution must not replace the answers that policy checked.
    dns = MagicMock(
        side_effect=[
            [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))
                for ip in addresses
            ],
            AssertionError("Destination was resolved twice"),
        ]
    )
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    result = resolve_sandbox_destination(
        ("::ffff:10.0.0.1", 1234),
        "https",
        "private-mcp.test",
        443,
        config=parse_destination_policy(api_url),
        resolve_sandbox=identity,
        mcp_resolver=mcp,
    )

    assert result == (tuple(addresses) if allowed else None)
    dns.assert_called_once()
    if needs_mcp:
        identity.assert_called_once_with("10.0.0.1")
        access.assert_called_once_with(sandbox, "https", "private-mcp.test", 443)
    else:
        identity.assert_not_called()
        access.assert_not_called()
