"""Unit tests for Prometheus instrumentation module."""

import threading
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from prometheus_client import Gauge

from onyx.server.metrics.per_tenant import per_tenant_request_callback
from onyx.server.metrics.prometheus_setup import setup_prometheus_metrics
from onyx.server.metrics.slow_requests import slow_request_callback


def _make_info(
    duration: float,
    method: str = "GET",
    handler: str = "/api/test",
    status: str = "200",
) -> Any:
    """Build a fake metrics Info object matching the instrumentator's Info shape."""
    return MagicMock(
        modified_duration=duration,
        method=method,
        modified_handler=handler,
        modified_status=status,
    )


def test_slow_request_callback_increments_above_threshold() -> None:
    with patch("onyx.server.metrics.slow_requests._slow_requests") as mock_counter:
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        info = _make_info(
            duration=2.0, method="POST", handler="/api/chat", status="200"
        )
        slow_request_callback(info)

        mock_counter.labels.assert_called_once_with(
            method="POST", handler="/api/chat", status="200"
        )
        mock_labels.inc.assert_called_once()


def test_slow_request_callback_skips_below_threshold() -> None:
    with patch("onyx.server.metrics.slow_requests._slow_requests") as mock_counter:
        info = _make_info(duration=0.5)
        slow_request_callback(info)

        mock_counter.labels.assert_not_called()


def test_slow_request_callback_skips_at_exact_threshold() -> None:
    with (
        patch("onyx.server.metrics.slow_requests.SLOW_REQUEST_THRESHOLD_SECONDS", 1.0),
        patch("onyx.server.metrics.slow_requests._slow_requests") as mock_counter,
    ):
        info = _make_info(duration=1.0)
        slow_request_callback(info)

        mock_counter.labels.assert_not_called()


def test_setup_attaches_instrumentator_to_app() -> None:
    with patch("onyx.server.metrics.prometheus_setup.Instrumentator") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.instrument.return_value = mock_instance
        mock_cls.return_value = mock_instance

        app = FastAPI()
        setup_prometheus_metrics(app)

        mock_cls.assert_called_once_with(
            should_group_status_codes=False,
            should_ignore_untemplated=False,
            should_group_untemplated=True,
            should_instrument_requests_inprogress=True,
            inprogress_labels=True,
            excluded_handlers=["/health", "/metrics", "/openapi.json"],
        )
        assert mock_instance.add.call_count == 3
        mock_instance.instrument.assert_called_once_with(
            app,
            latency_lowr_buckets=(
                0.01,
                0.025,
                0.05,
                0.1,
                0.25,
                0.5,
                1.0,
                2.5,
                5.0,
                10.0,
            ),
        )
        mock_instance.expose.assert_called_once_with(app)


def test_per_tenant_callback_increments_with_tenant_id() -> None:
    """Verify per-tenant callback reads tenant from contextvar and increments."""
    with (
        patch(
            "onyx.server.metrics.per_tenant.CURRENT_TENANT_ID_CONTEXTVAR"
        ) as mock_ctx,
        patch("onyx.server.metrics.per_tenant._requests_by_tenant") as mock_counter,
    ):
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels
        mock_ctx.get.return_value = "tenant_abc"

        info = _make_info(
            duration=0.1, method="POST", handler="/api/chat", status="200"
        )
        per_tenant_request_callback(info)

        mock_counter.labels.assert_called_once_with(
            tenant_id="tenant_abc",
            method="POST",
            handler="/api/chat",
            status="200",
        )
        mock_labels.inc.assert_called_once()


def test_per_tenant_callback_falls_back_to_unknown() -> None:
    """Verify per-tenant callback uses 'unknown' when contextvar is None."""
    with (
        patch(
            "onyx.server.metrics.per_tenant.CURRENT_TENANT_ID_CONTEXTVAR"
        ) as mock_ctx,
        patch("onyx.server.metrics.per_tenant._requests_by_tenant") as mock_counter,
    ):
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels
        mock_ctx.get.return_value = None

        info = _make_info(duration=0.1)
        per_tenant_request_callback(info)

        mock_counter.labels.assert_called_once_with(
            tenant_id="unknown",
            method="GET",
            handler="/api/test",
            status="200",
        )
        mock_labels.inc.assert_called_once()


def test_inprogress_gauge_increments_during_request() -> None:
    """Verify the in-progress gauge goes up while a request is in flight."""
    registry = CollectorRegistry()
    gauge = Gauge(
        "http_requests_inprogress_test",
        "In-progress requests",
        ["method", "handler"],
        registry=registry,
    )

    request_started = threading.Event()
    request_release = threading.Event()

    app = FastAPI()

    @app.get("/slow")
    def slow_endpoint() -> dict:
        gauge.labels(method="GET", handler="/slow").inc()
        request_started.set()
        request_release.wait(timeout=5)
        gauge.labels(method="GET", handler="/slow").dec()
        return {"status": "done"}

    client = TestClient(app, raise_server_exceptions=False)

    def make_request() -> None:
        client.get("/slow")

    thread = threading.Thread(target=make_request)
    thread.start()

    request_started.wait(timeout=5)
    assert gauge.labels(method="GET", handler="/slow")._value.get() == 1.0

    request_release.set()
    thread.join(timeout=5)
    assert gauge.labels(method="GET", handler="/slow")._value.get() == 0.0


def test_inprogress_gauge_tracks_concurrent_requests() -> None:
    """Verify the gauge correctly counts multiple concurrent in-flight requests."""
    registry = CollectorRegistry()
    gauge = Gauge(
        "http_requests_inprogress_concurrent_test",
        "In-progress requests",
        ["method", "handler"],
        registry=registry,
    )

    # 3 parties: 2 request threads + main thread
    barrier = threading.Barrier(3)
    release = threading.Event()

    app = FastAPI()

    @app.get("/concurrent")
    def concurrent_endpoint() -> dict:
        gauge.labels(method="GET", handler="/concurrent").inc()
        barrier.wait(timeout=5)
        release.wait(timeout=5)
        gauge.labels(method="GET", handler="/concurrent").dec()
        return {"status": "done"}

    client = TestClient(app, raise_server_exceptions=False)

    def make_request() -> None:
        client.get("/concurrent")

    t1 = threading.Thread(target=make_request)
    t2 = threading.Thread(target=make_request)
    t1.start()
    t2.start()

    # All 3 threads meet here — both requests are in-flight
    barrier.wait(timeout=5)
    assert gauge.labels(method="GET", handler="/concurrent")._value.get() == 2.0

    release.set()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert gauge.labels(method="GET", handler="/concurrent")._value.get() == 0.0
