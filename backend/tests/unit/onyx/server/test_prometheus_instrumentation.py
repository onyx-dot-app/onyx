"""Unit tests for Prometheus instrumentation module."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import FastAPI

from onyx.server.prometheus_instrumentation import _slow_request_callback
from onyx.server.prometheus_instrumentation import setup_fastapi_instrumentation


def _make_info(
    duration: float,
    method: str = "GET",
    handler: str = "/api/test",
    status: str = "200",
) -> SimpleNamespace:
    """Build a fake metrics Info object."""
    return SimpleNamespace(
        modified_duration=duration,
        method=method,
        modified_handler=handler,
        modified_status=status,
    )


def test_slow_request_callback_increments_above_threshold() -> None:
    with patch("onyx.server.prometheus_instrumentation._slow_requests") as mock_counter:
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        info = _make_info(
            duration=2.0, method="POST", handler="/api/chat", status="200"
        )
        _slow_request_callback(info)  # type: ignore

        mock_counter.labels.assert_called_once_with(
            method="POST", handler="/api/chat", status="200"
        )
        mock_labels.inc.assert_called_once()


def test_slow_request_callback_skips_below_threshold() -> None:
    with patch("onyx.server.prometheus_instrumentation._slow_requests") as mock_counter:
        info = _make_info(duration=0.5)
        _slow_request_callback(info)  # type: ignore

        mock_counter.labels.assert_not_called()


def test_slow_request_callback_skips_at_exact_threshold() -> None:
    with (
        patch(
            "onyx.server.prometheus_instrumentation.SLOW_REQUEST_THRESHOLD_SECONDS", 1.0
        ),
        patch("onyx.server.prometheus_instrumentation._slow_requests") as mock_counter,
    ):
        info = _make_info(duration=1.0)
        _slow_request_callback(info)  # type: ignore

        mock_counter.labels.assert_not_called()


def test_setup_attaches_instrumentator_to_app() -> None:
    with patch("onyx.server.prometheus_instrumentation.Instrumentator") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.instrument.return_value = mock_instance
        mock_cls.return_value = mock_instance

        app = FastAPI()
        setup_fastapi_instrumentation(app)

        mock_cls.assert_called_once_with(
            should_group_status_codes=False,
            should_ignore_untemplated=False,
            should_group_untemplated=True,
            should_instrument_requests_inprogress=True,
            inprogress_labels=True,
            excluded_handlers=["/health", "/metrics", "/openapi.json"],
        )
        mock_instance.add.assert_called_once()
        mock_instance.instrument.assert_called_once_with(app)
        mock_instance.expose.assert_called_once_with(app)
