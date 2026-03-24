"""Tests for the Prometheus metrics server module."""

from collections.abc import Iterator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.server.metrics.metrics_server import _DEFAULT_PORTS
from onyx.server.metrics.metrics_server import start_metrics_server


@pytest.fixture(autouse=True)
def reset_server_state() -> Iterator[None]:
    """Reset the global _server_started between tests."""
    import onyx.server.metrics.metrics_server as mod

    mod._server_started = False
    yield
    mod._server_started = False


class TestStartMetricsServer:
    @patch("onyx.server.metrics.metrics_server.start_http_server")
    def test_uses_default_port_for_known_worker(self, mock_start: MagicMock) -> None:
        port = start_metrics_server("monitoring")
        assert port == _DEFAULT_PORTS["monitoring"]
        mock_start.assert_called_once_with(_DEFAULT_PORTS["monitoring"])

    @patch("onyx.server.metrics.metrics_server.start_http_server")
    @patch.dict("os.environ", {"PROMETHEUS_METRICS_PORT": "9999"})
    def test_env_var_overrides_default(self, mock_start: MagicMock) -> None:
        port = start_metrics_server("monitoring")
        assert port == 9999
        mock_start.assert_called_once_with(9999)

    @patch("onyx.server.metrics.metrics_server.start_http_server")
    @patch.dict("os.environ", {"PROMETHEUS_METRICS_ENABLED": "false"})
    def test_disabled_via_env_var(self, mock_start: MagicMock) -> None:
        port = start_metrics_server("monitoring")
        assert port is None
        mock_start.assert_not_called()

    @patch("onyx.server.metrics.metrics_server.start_http_server")
    def test_unknown_worker_type_no_env_var(self, mock_start: MagicMock) -> None:
        port = start_metrics_server("unknown_worker")
        assert port is None
        mock_start.assert_not_called()

    @patch("onyx.server.metrics.metrics_server.start_http_server")
    def test_idempotent(self, mock_start: MagicMock) -> None:
        port1 = start_metrics_server("monitoring")
        port2 = start_metrics_server("monitoring")
        assert port1 == _DEFAULT_PORTS["monitoring"]
        assert port2 is None
        mock_start.assert_called_once()

    @patch("onyx.server.metrics.metrics_server.start_http_server")
    def test_handles_os_error(self, mock_start: MagicMock) -> None:
        mock_start.side_effect = OSError("Address already in use")
        port = start_metrics_server("monitoring")
        assert port is None
