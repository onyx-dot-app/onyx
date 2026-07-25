"""Standalone Prometheus metrics HTTP server for non-API processes.

The FastAPI API server already exposes /metrics via prometheus-fastapi-instrumentator.
Celery workers and other background processes use this module to expose their
own /metrics endpoint on a configurable port.

The listener binds the IPv6 wildcard with IPV6_V6ONLY cleared, so a single socket
serves both IPv4 and IPv6 scrapers. Hosts without usable IPv6 fall back to the
IPv4 wildcard.

Usage:
    from onyx.server.metrics.metrics_server import start_metrics_server
    start_metrics_server("monitoring")  # reads port from env or uses default
"""

import os
import socket
import threading
from socketserver import ThreadingMixIn
from typing import Any, cast
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

from prometheus_client import make_wsgi_app

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
    "scheduled_tasks": 9098,
}

# Tried in order. The IPv6 wildcard is dual-stack (see _DualStackWSGIServer) and
# serves both families, including on hosts where net.ipv6.conf.all.disable_ipv6=1
# (binding "::" still succeeds there). The IPv4 wildcard is insurance for the
# narrower case of a kernel built or booted without AF_INET6 at all, where
# creating the socket fails outright.
# Binding all interfaces is intended: /metrics is scraped from off-pod.
_BIND_ADDRESS_CANDIDATES: tuple[str, ...] = ("::", "0.0.0.0")  # noqa: S104

_server_started = False
_server_lock = threading.Lock()
_httpd: WSGIServer | None = None


class _SilentHandler(WSGIRequestHandler):
    """Drops per-request access logs; Prometheus scrapes every few seconds."""

    def log_message(self, format: str, *args: Any) -> None:
        pass


class _DualStackWSGIServer(ThreadingMixIn, WSGIServer):
    """Threaded WSGI server that serves IPv4 and IPv6 from a single socket.

    An AF_INET6 listener only answers IPv4 scrapes when IPV6_V6ONLY is unset,
    which otherwise defaults from the host's net.ipv6.bindv6only sysctl (and its
    equivalents on other platforms). Clearing the option here makes dual-stack a
    property of this server rather than of the host it happens to run on.
    """

    daemon_threads = True

    def server_bind(self) -> None:
        if self.address_family == socket.AF_INET6:
            try:
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except OSError as e:
                # Some kernels pin IPv6 sockets to v6-only and refuse this. Keep
                # the listener rather than failing over to 0.0.0.0: on an
                # IPv6-only cluster that fallback binds successfully but no
                # scraper can route to it, which is strictly worse than serving
                # IPv6 alone. Warn so the reduced reachability is not silent.
                logger.warning(
                    "Metrics socket could not be made dual-stack (%s); this "
                    "listener will serve IPv6 scrapes only.",
                    e,
                )
        super().server_bind()


def _format_endpoint(addr: str, port: int) -> str:
    """Render addr:port, bracketing IPv6 so "::" does not log as ":::9097"."""
    return f"[{addr}]:{port}" if ":" in addr else f"{addr}:{port}"


def _start_wsgi_server(addr: str, port: int) -> WSGIServer:
    """Bind a metrics server on addr:port, serving from a daemon thread."""
    # WSGIServer hardcodes AF_INET, which cannot bind an IPv6 address, so the
    # family has to be resolved from the address first.
    infos = socket.getaddrinfo(
        addr, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE
    )
    if not infos:
        # Every failure in here has to surface as OSError, or the caller skips
        # its fallback to the next candidate.
        raise OSError(f"getaddrinfo returned no results for {addr!r}")
    family, _, _, _, sockaddr = infos[0]

    class _Server(_DualStackWSGIServer):
        address_family = family

    # Bind the sockaddr getaddrinfo produced rather than just its host part, so a
    # scoped IPv6 address (fe80::1%eth0) keeps the scope id it needs to bind.
    # This is make_server() inlined; it accepts only a (host, port) pair.
    # The cast drops getaddrinfo's link-layer sockaddr form, which SOCK_STREAM
    # over an IP address cannot return.
    address = cast("tuple[str, int] | tuple[str, int, int, int]", sockaddr)
    httpd = _Server(address, _SilentHandler)
    try:
        httpd.set_app(make_wsgi_app())
        threading.Thread(
            target=httpd.serve_forever, daemon=True, name=f"prometheus-metrics-{port}"
        ).start()
    except BaseException:
        # The socket is already listening by the time _Server() returns, and
        # TCPServer only cleans up failures raised inside its own bind/activate.
        httpd.server_close()
        raise
    return httpd


def start_metrics_server(worker_type: str) -> int | None:
    """Start a Prometheus metrics HTTP server in a background thread.

    Returns the port if started, None if disabled or already started.

    Port resolution order:
    1. PROMETHEUS_METRICS_PORT env var (explicit override)
    2. Default port for the worker type
    3. If worker type is unknown and no env var, skip

    Set PROMETHEUS_METRICS_ENABLED=false to disable.
    Set PROMETHEUS_METRICS_BIND_ADDR to pin the bind address (disables fallback).
    """
    global _server_started
    global _httpd

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

        bind_override = os.environ.get("PROMETHEUS_METRICS_BIND_ADDR", "").strip()
        candidates = (bind_override,) if bind_override else _BIND_ADDRESS_CANDIDATES

        last_error: Exception | None = None
        for index, addr in enumerate(candidates):
            try:
                _httpd = _start_wsgi_server(addr, port)
            except OSError as e:
                last_error = e
                remaining = candidates[index + 1 :]
                if remaining:
                    logger.warning(
                        "Metrics server for %s could not bind %s (%s). Falling back to %s.",
                        worker_type,
                        _format_endpoint(addr, port),
                        e,
                        _format_endpoint(remaining[0], port),
                    )
                continue
            except Exception as e:
                # Workers call this from worker_ready without guarding it, and
                # metrics are best-effort, so an unexpected failure here must not
                # stop the worker from starting.
                last_error = e
                logger.exception(
                    "Unexpected error starting metrics server for %s on %s",
                    worker_type,
                    _format_endpoint(addr, port),
                )
                continue

            _server_started = True
            logger.info(
                "Prometheus metrics server started on %s for %s",
                _format_endpoint(addr, port),
                worker_type,
            )
            return port

        logger.warning(
            "Failed to start metrics server for %s (tried %s): %s",
            worker_type,
            ", ".join(_format_endpoint(a, port) for a in candidates),
            last_error,
        )
        return None
