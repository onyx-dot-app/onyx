"""Standalone Prometheus metrics HTTP server for non-API processes.

The FastAPI API server already exposes /metrics via prometheus-fastapi-instrumentator.
Celery workers and other background processes use this module to expose their
own /metrics endpoint on a configurable port.

Usage:
    from onyx.server.metrics.metrics_server import start_metrics_server
    start_metrics_server("monitoring")  # reads port from env or uses default
"""

import os
import threading

from prometheus_client import start_http_server

from onyx.utils.logger import setup_logger

logger = setup_logger()

# Default ports for worker types that serve custom Prometheus metrics.
# Only add entries here when a worker actually registers collectors.
# In k8s each worker type runs in its own pod, so PROMETHEUS_METRICS_PORT
# env var can override.
_DEFAULT_PORTS: dict[str, int] = {
    "monitoring": 9096,
    "docfetching": 9092,
    "docprocessing": 9093,
    "heavy": 9094,
    "light": 9095,
    "primary": 9097,
}

_server_started = False
_server_lock = threading.Lock()


def start_metrics_server(worker_type: str) -> int | None:
    """Start a Prometheus metrics HTTP server in a background thread.

    Returns the port if started, None if disabled or already started.

    Port resolution order:
    1. PROMETHEUS_METRICS_PORT env var (explicit override)
    2. Default port for the worker type
    3. If worker type is unknown and no env var, skip

    Set PROMETHEUS_METRICS_ENABLED=false to disable.
    """
    global _server_started

    with _server_lock:
        if _server_started:
            logger.debug("Metrics server already started for %s", worker_type)
            return None

        enabled = os.environ.get("PROMETHEUS_METRICS_ENABLED", "true").lower()
        if enabled in ("false", "0", "no"):
            logger.info("Prometheus metrics server disabled for %s", worker_type)
            return None

        port_str = os.environ.get("PROMETHEUS_METRICS_PORT")
        if port_str:
            try:
                port = int(port_str)
            except ValueError:
                logger.warning(
                    "Invalid PROMETHEUS_METRICS_PORT '%s' for %s, must be a numeric port. Skipping metrics server.",
                    port_str,
                    worker_type,
                )
                return None
        elif worker_type in _DEFAULT_PORTS:
            port = _DEFAULT_PORTS[worker_type]
        else:
            logger.info(
                "No default metrics port for worker type '%s' and PROMETHEUS_METRICS_PORT not set. Skipping metrics server.",
                worker_type,
            )
            return None

        try:
            start_http_server(port)
            _server_started = True
            logger.info(
                "Prometheus metrics server started on :%s for %s", port, worker_type
            )
            return port
        except OSError as e:
            logger.warning(
                "Failed to start metrics server on :%s for %s: %s", port, worker_type, e
            )
            return None
