"""Unit tests for SQLAlchemy connection pool Prometheus metrics."""

import time
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import FastAPI
from sqlalchemy.pool import NullPool

from onyx.server.metrics.postgres_connection_pool import _register_pool_events
from onyx.server.metrics.postgres_connection_pool import PoolStateCollector
from onyx.server.metrics.postgres_connection_pool import (
    setup_postgres_connection_pool_metrics,
)
from onyx.utils.middleware import _build_route_map
from onyx.utils.middleware import _match_route


# --- PoolStateCollector tests ---


def test_pool_state_collector_reports_pool_stats() -> None:
    """Verify the custom collector reads pool.checkedout/checkedin/overflow/size."""
    mock_pool = MagicMock()
    mock_pool.checkedout.return_value = 5
    mock_pool.checkedin.return_value = 35
    mock_pool.overflow.return_value = 2
    mock_pool.size.return_value = 40

    collector = PoolStateCollector()
    collector.add_pool("sync", mock_pool)

    families = collector.collect()
    # 4 GaugeMetricFamilies: checked_out, checked_in, overflow, size
    assert len(families) == 4

    # Convert to dict for easier assertions
    metrics: dict[str, float] = {}
    for family in families:
        for sample in family.samples:
            metrics[f"{sample.name}:{sample.labels['engine']}"] = sample.value

    assert metrics["onyx_db_pool_checked_out:sync"] == 5
    assert metrics["onyx_db_pool_checked_in:sync"] == 35
    assert metrics["onyx_db_pool_overflow:sync"] == 2
    assert metrics["onyx_db_pool_size:sync"] == 40


def test_pool_state_collector_handles_multiple_engines() -> None:
    """Verify the collector reports metrics for multiple engines."""
    sync_pool = MagicMock()
    sync_pool.checkedout.return_value = 10
    sync_pool.checkedin.return_value = 30
    sync_pool.overflow.return_value = 0
    sync_pool.size.return_value = 40

    readonly_pool = MagicMock()
    readonly_pool.checkedout.return_value = 3
    readonly_pool.checkedin.return_value = 7
    readonly_pool.overflow.return_value = 1
    readonly_pool.size.return_value = 10

    collector = PoolStateCollector()
    collector.add_pool("sync", sync_pool)
    collector.add_pool("readonly", readonly_pool)

    families = collector.collect()
    # Each family should have 2 samples (sync + readonly)
    for family in families:
        assert len(list(family.samples)) == 2


# --- Pool event listener tests ---


def _make_conn_record() -> MagicMock:
    """Create a mock connection record with an info dict."""
    record = MagicMock()
    record.info = {}
    return record


def test_checkout_event_stores_endpoint_and_increments_gauge() -> None:
    """Verify checkout event stores handler on conn_record and increments metrics."""
    engine = MagicMock()
    engine.pool = MagicMock()
    listeners: dict[str, Any] = {}

    # Capture event listeners
    with patch("onyx.server.metrics.postgres_connection_pool.event") as mock_event:

        def capture_listener(target: Any, event_name: str) -> Any:  # noqa: ARG001
            def decorator(fn: Any) -> Any:
                listeners[event_name] = fn
                return fn

            return decorator

        mock_event.listens_for.side_effect = capture_listener
        _register_pool_events(engine, "sync")

    conn_record = _make_conn_record()

    with (
        patch(
            "onyx.server.metrics.postgres_connection_pool.CURRENT_ENDPOINT_CONTEXTVAR"
        ) as mock_ctx,
        patch(
            "onyx.server.metrics.postgres_connection_pool._connections_held"
        ) as mock_gauge,
        patch("onyx.server.metrics.postgres_connection_pool._checkout_total"),
    ):
        mock_labels = MagicMock()
        mock_gauge.labels.return_value = mock_labels
        mock_ctx.get.return_value = "/api/chat/send-message"
        listeners["checkout"](None, conn_record, None)

    assert conn_record.info["_metrics_endpoint"] == "/api/chat/send-message"
    assert "_metrics_checkout_time" in conn_record.info
    mock_gauge.labels.assert_called_with(
        handler="/api/chat/send-message", engine="sync"
    )
    mock_labels.inc.assert_called_once()


def test_checkin_event_observes_hold_duration() -> None:
    """Verify checkin event reads endpoint from conn_record and observes hold time."""
    engine = MagicMock()
    engine.pool = MagicMock()
    listeners: dict[str, Any] = {}

    with patch("onyx.server.metrics.postgres_connection_pool.event") as mock_event:

        def capture_listener(target: Any, event_name: str) -> Any:  # noqa: ARG001
            def decorator(fn: Any) -> Any:
                listeners[event_name] = fn
                return fn

            return decorator

        mock_event.listens_for.side_effect = capture_listener
        _register_pool_events(engine, "sync")

    conn_record = _make_conn_record()
    conn_record.info["_metrics_endpoint"] = "/api/search"
    conn_record.info["_metrics_checkout_time"] = time.monotonic() - 0.5

    with (
        patch(
            "onyx.server.metrics.postgres_connection_pool._connections_held"
        ) as mock_gauge,
        patch(
            "onyx.server.metrics.postgres_connection_pool._hold_seconds"
        ) as mock_hist,
        patch("onyx.server.metrics.postgres_connection_pool._checkin_total"),
    ):
        mock_labels = MagicMock()
        mock_gauge.labels.return_value = mock_labels
        mock_hist_labels = MagicMock()
        mock_hist.labels.return_value = mock_hist_labels

        listeners["checkin"](None, conn_record)

        mock_gauge.labels.assert_called_with(handler="/api/search", engine="sync")
        mock_labels.dec.assert_called_once()
        mock_hist.labels.assert_called_with(handler="/api/search", engine="sync")
        mock_hist_labels.observe.assert_called_once()
        # Verify the observed duration is roughly 0.5s
        observed = mock_hist_labels.observe.call_args[0][0]
        assert 0.4 < observed < 1.0

    # conn_record.info should be cleaned up
    assert "_metrics_endpoint" not in conn_record.info
    assert "_metrics_checkout_time" not in conn_record.info


def test_checkin_with_missing_endpoint_uses_unknown() -> None:
    """Verify checkin gracefully handles missing endpoint info."""
    engine = MagicMock()
    engine.pool = MagicMock()
    listeners: dict[str, Any] = {}

    with patch("onyx.server.metrics.postgres_connection_pool.event") as mock_event:

        def capture_listener(target: Any, event_name: str) -> Any:  # noqa: ARG001
            def decorator(fn: Any) -> Any:
                listeners[event_name] = fn
                return fn

            return decorator

        mock_event.listens_for.side_effect = capture_listener
        _register_pool_events(engine, "sync")

    conn_record = _make_conn_record()

    with (
        patch(
            "onyx.server.metrics.postgres_connection_pool._connections_held"
        ) as mock_gauge,
        patch("onyx.server.metrics.postgres_connection_pool._hold_seconds"),
        patch("onyx.server.metrics.postgres_connection_pool._checkin_total"),
    ):
        mock_labels = MagicMock()
        mock_gauge.labels.return_value = mock_labels

        listeners["checkin"](None, conn_record)

        mock_gauge.labels.assert_called_with(handler="unknown", engine="sync")


# --- setup_postgres_connection_pool_metrics tests ---


def test_setup_skips_null_pool_engines() -> None:
    """Verify setup_postgres_connection_pool_metrics skips engines with NullPool."""
    with (
        patch("onyx.server.metrics.postgres_connection_pool.REGISTRY"),
        patch(
            "onyx.server.metrics.postgres_connection_pool._register_pool_events"
        ) as mock_register,
    ):
        null_engine = MagicMock()
        null_engine.pool = MagicMock(spec=NullPool)

        setup_postgres_connection_pool_metrics({"null": null_engine})
        mock_register.assert_not_called()


# --- Route matching tests ---


def test_build_route_map_extracts_api_routes() -> None:
    """Verify _build_route_map extracts APIRoute path regexes."""
    app = FastAPI()

    @app.get("/api/test")
    def test_endpoint() -> dict:
        return {}

    @app.get("/api/items/{item_id}")
    def get_item(item_id: str) -> dict:  # noqa: ARG001
        return {}

    route_map = _build_route_map(app)
    # Should have at least the 2 routes we defined
    templates = [template for _, template in route_map]
    assert "/api/test" in templates
    assert "/api/items/{item_id}" in templates


def test_match_route_resolves_parameterized_paths() -> None:
    """Verify _match_route resolves /api/items/abc-123 to /api/items/{item_id}."""
    app = FastAPI()

    @app.get("/api/items/{item_id}")
    def get_item(item_id: str) -> dict:  # noqa: ARG001
        return {}

    route_map = _build_route_map(app)
    result = _match_route(route_map, "/api/items/abc-123")
    assert result == "/api/items/{item_id}"


def test_match_route_returns_none_for_unknown_paths() -> None:
    """Verify _match_route returns None for paths not in the route map."""
    app = FastAPI()

    @app.get("/api/test")
    def test_endpoint() -> dict:
        return {}

    route_map = _build_route_map(app)
    result = _match_route(route_map, "/api/nonexistent")
    assert result is None


def test_match_route_exact_paths() -> None:
    """Verify _match_route handles exact (non-parameterized) paths."""
    app = FastAPI()

    @app.get("/api/health")
    def health() -> dict:
        return {}

    route_map = _build_route_map(app)
    result = _match_route(route_map, "/api/health")
    assert result == "/api/health"
