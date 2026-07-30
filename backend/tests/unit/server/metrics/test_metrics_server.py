"""Tests for the Prometheus metrics server module."""

import socket
import urllib.request
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch
from wsgiref.simple_server import WSGIServer

import pytest

from onyx.server.metrics.metrics_server import _DEFAULT_PORTS, start_metrics_server


@pytest.fixture(autouse=True)
def reset_server_state() -> Iterator[None]:
    """Reset the global server state between tests."""
    import onyx.server.metrics.metrics_server as mod

    def _teardown() -> None:
        if mod._httpd is not None:
            mod._httpd.shutdown()
            mod._httpd.server_close()
            mod._httpd = None
        mod._server_started = False

    _teardown()
    yield
    _teardown()


def _free_port() -> int:
    """Reserve an ephemeral port, then release it for the server under test."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _ipv6_loopback_available() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


def _scrape(host: str, port: int) -> int:
    with urllib.request.urlopen(f"http://{host}:{port}/metrics", timeout=5) as resp:
        return int(resp.status)


class TestStartMetricsServer:
    @patch("onyx.server.metrics.metrics_server._start_wsgi_server")
    def test_uses_default_port_for_known_worker(self, mock_start: MagicMock) -> None:
        port = start_metrics_server("monitoring")
        assert port == _DEFAULT_PORTS["monitoring"]
        mock_start.assert_called_once_with("::", _DEFAULT_PORTS["monitoring"])

    @patch("onyx.server.metrics.metrics_server._start_wsgi_server")
    @patch.dict("os.environ", {"PROMETHEUS_METRICS_PORT": "9999"})
    def test_env_var_overrides_default(self, mock_start: MagicMock) -> None:
        port = start_metrics_server("monitoring")
        assert port == 9999
        mock_start.assert_called_once_with("::", 9999)

    @patch("onyx.server.metrics.metrics_server._start_wsgi_server")
    @patch.dict("os.environ", {"PROMETHEUS_METRICS_ENABLED": "false"})
    def test_disabled_via_env_var(self, mock_start: MagicMock) -> None:
        port = start_metrics_server("monitoring")
        assert port is None
        mock_start.assert_not_called()

    @patch("onyx.server.metrics.metrics_server._start_wsgi_server")
    def test_unknown_worker_type_no_env_var(self, mock_start: MagicMock) -> None:
        port = start_metrics_server("unknown_worker")
        assert port is None
        mock_start.assert_not_called()

    @patch("onyx.server.metrics.metrics_server._start_wsgi_server")
    def test_idempotent(self, mock_start: MagicMock) -> None:
        port1 = start_metrics_server("monitoring")
        port2 = start_metrics_server("monitoring")
        assert port1 == _DEFAULT_PORTS["monitoring"]
        assert port2 is None
        mock_start.assert_called_once()

    @patch("onyx.server.metrics.metrics_server._start_wsgi_server")
    def test_handles_os_error(self, mock_start: MagicMock) -> None:
        mock_start.side_effect = OSError("Address already in use")
        port = start_metrics_server("monitoring")
        assert port is None
        # Both wildcards are attempted before giving up.
        assert mock_start.call_count == 2

    @patch("onyx.server.metrics.metrics_server._start_wsgi_server")
    @patch.dict("os.environ", {"PROMETHEUS_METRICS_PORT": "not_a_number"})
    def test_invalid_port_env_var_returns_none(self, mock_start: MagicMock) -> None:
        port = start_metrics_server("monitoring")
        assert port is None
        mock_start.assert_not_called()


class TestBindAddressSelection:
    @patch("onyx.server.metrics.metrics_server._start_wsgi_server")
    def test_falls_back_to_ipv4_when_ipv6_unavailable(
        self, mock_start: MagicMock
    ) -> None:
        """IPv6-disabled hosts must keep serving metrics over IPv4."""

        def side_effect(addr: str, _port: int) -> MagicMock:
            if addr == "::":
                raise OSError("Address family not supported by protocol")
            return MagicMock()

        mock_start.side_effect = side_effect

        port = start_metrics_server("monitoring")
        assert port == _DEFAULT_PORTS["monitoring"]
        assert [call.args[0] for call in mock_start.call_args_list] == ["::", "0.0.0.0"]

    @patch("onyx.server.metrics.metrics_server._start_wsgi_server")
    def test_unexpected_error_does_not_stop_the_worker(
        self, mock_start: MagicMock
    ) -> None:
        """Workers call this unguarded from worker_ready; metrics are best-effort."""
        mock_start.side_effect = RuntimeError("can't start new thread")
        assert start_metrics_server("monitoring") is None

    def test_empty_getaddrinfo_surfaces_as_os_error(self) -> None:
        """A non-OSError here would bypass the fallback and reach the worker."""
        import onyx.server.metrics.metrics_server as mod

        with patch.object(socket, "getaddrinfo", return_value=[]):
            with pytest.raises(OSError):
                mod._start_wsgi_server("::", 9099)

    @patch("onyx.server.metrics.metrics_server._start_wsgi_server")
    @patch.dict("os.environ", {"PROMETHEUS_METRICS_BIND_ADDR": "127.0.0.1"})
    def test_explicit_bind_addr_is_pinned(self, mock_start: MagicMock) -> None:
        """An explicit bind address is honored verbatim, with no fallback."""
        port = start_metrics_server("monitoring")
        assert port == _DEFAULT_PORTS["monitoring"]
        mock_start.assert_called_once_with("127.0.0.1", _DEFAULT_PORTS["monitoring"])


class TestDualStackListener:
    """Exercises a real socket rather than asserting on call arguments."""

    def test_server_bind_clears_v6only_before_binding(self) -> None:
        """Dual-stack must be set by us, not inherited from net.ipv6.bindv6only.

        Ordering is the load-bearing part: setsockopt(IPV6_V6ONLY) on an
        already-bound socket fails with EINVAL, so clearing it after the bind
        would silently leave the listener v6-only. Asserted against a stub
        socket so this holds on hosts whose sysctl already defaults to 0 and
        would otherwise mask both mistakes.
        """
        import onyx.server.metrics.metrics_server as mod

        parent = MagicMock()
        server = object.__new__(mod._DualStackWSGIServer)
        server.address_family = socket.AF_INET6
        server.socket = parent.socket

        with patch.object(WSGIServer, "server_bind", parent.server_bind):
            server.server_bind()

        assert [call[0] for call in parent.mock_calls] == [
            "socket.setsockopt",
            "server_bind",
        ]
        parent.socket.setsockopt.assert_called_once_with(
            socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0
        )

    def test_server_bind_keeps_listener_when_v6only_cannot_be_cleared(self) -> None:
        """A kernel that pins v6-only must not cost us the IPv6 listener.

        Failing over to 0.0.0.0 here would bind successfully on an IPv6-only
        cluster while being unroutable for every scraper, so the bind proceeds
        and the reduced reachability is warned about instead.
        """
        import onyx.server.metrics.metrics_server as mod

        server = object.__new__(mod._DualStackWSGIServer)
        server.address_family = socket.AF_INET6
        server.socket = MagicMock()
        server.socket.setsockopt.side_effect = OSError("Protocol not available")

        bound = MagicMock()
        with patch.object(WSGIServer, "server_bind", bound):
            with patch.object(mod.logger, "warning") as warn:
                server.server_bind()  # must not raise

        bound.assert_called_once()
        assert warn.call_count == 1

    def test_server_bind_leaves_ipv4_socket_alone(self) -> None:
        """An AF_INET listener has no IPV6_V6ONLY option to set."""
        import onyx.server.metrics.metrics_server as mod

        server = object.__new__(mod._DualStackWSGIServer)
        server.address_family = socket.AF_INET
        server.socket = MagicMock()

        with patch.object(WSGIServer, "server_bind", lambda _self: None):
            server.server_bind()

        server.socket.setsockopt.assert_not_called()

    @pytest.mark.skipif(
        not _ipv6_loopback_available(), reason="IPv6 loopback unavailable"
    )
    def test_serves_both_ipv4_and_ipv6_scrapers(self) -> None:
        import onyx.server.metrics.metrics_server as mod

        port = _free_port()
        with patch.dict("os.environ", {"PROMETHEUS_METRICS_PORT": str(port)}):
            assert start_metrics_server("monitoring") == port

        assert mod._httpd is not None
        assert mod._httpd.socket.family == socket.AF_INET6
        # The guarantee this module makes, independent of net.ipv6.bindv6only.
        assert (
            mod._httpd.socket.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 0
        )

        assert _scrape("127.0.0.1", port) == 200
        assert _scrape("[::1]", port) == 200

    @pytest.mark.skipif(
        not _ipv6_loopback_available(), reason="IPv6 loopback unavailable"
    )
    def test_full_sockaddr_reaches_bind(self) -> None:
        """The whole getaddrinfo sockaddr must reach bind(), not just the host.

        Binding ::1 here, whose scope id is 0, so this checks the 4-tuple shape
        rather than a live scope id; passing the tuple through is what lets a
        scoped address like fe80::1%eth0 bind at all.
        """
        import onyx.server.metrics.metrics_server as mod

        captured: list[tuple[object, ...]] = []
        real_init = mod._DualStackWSGIServer.__init__

        def spy(self: Any, server_address: Any, *rest: Any) -> None:
            captured.append(tuple(server_address))
            real_init(self, server_address, *rest)

        port = _free_port()
        env = {
            "PROMETHEUS_METRICS_PORT": str(port),
            "PROMETHEUS_METRICS_BIND_ADDR": "::1",
        }
        with patch.object(mod._DualStackWSGIServer, "__init__", spy):
            with patch.dict("os.environ", env):
                assert start_metrics_server("monitoring") == port

        # getaddrinfo yields the 4-tuple (host, port, flowinfo, scope_id) for
        # IPv6; all four must survive to the socket rather than just the host.
        assert len(captured) == 1
        assert len(captured[0]) == 4
        assert _scrape("[::1]", port) == 200

    def test_pinned_ipv4_bind_stays_ipv4(self) -> None:
        """A pinned IPv4 address is respected rather than upgraded to IPv6."""
        import onyx.server.metrics.metrics_server as mod

        port = _free_port()
        env = {
            "PROMETHEUS_METRICS_PORT": str(port),
            "PROMETHEUS_METRICS_BIND_ADDR": "127.0.0.1",
        }
        with patch.dict("os.environ", env):
            assert start_metrics_server("monitoring") == port

        assert mod._httpd is not None
        assert mod._httpd.socket.family == socket.AF_INET
        assert _scrape("127.0.0.1", port) == 200
