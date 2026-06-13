"""Dev-mode opencode-serve connectivity for Docker sandboxes.

Full docker-compose deployments should use Docker bridge DNS:
``http://sandbox-<id>:4096``. Host-run local dev cannot resolve those Docker
network names. When ``docker_sandbox_manager`` decides dev-mode plumbing is
needed, it uses this module to publish opencode-serve on a random
localhost-bound host port and read that URL back from ``docker inspect``.
"""

from __future__ import annotations

from typing import Any

from onyx.server.features.build.configs import OPENCODE_SERVE_PORT

OPENCODE_SERVE_CONTAINER_PORT = f"{OPENCODE_SERVE_PORT}/tcp"
OPENCODE_SERVE_HOST_BIND_IP = "127.0.0.1"


def opencode_serve_port_bindings() -> dict[str, tuple[str, int | None]]:
    """Docker port bindings for host-run local dev."""
    return {OPENCODE_SERVE_CONTAINER_PORT: (OPENCODE_SERVE_HOST_BIND_IP, None)}


def published_opencode_serve_base_url(
    container_attrs: dict[str, Any],
) -> str | None:
    """Return the localhost-published opencode-serve URL from Docker attrs.

    Docker reports published ports under
    ``NetworkSettings.Ports["4096/tcp"]``. The sandbox binds the host side to
    127.0.0.1 with a random port, because local dev workers run on the host and
    cannot resolve sandbox container DNS names.
    """
    network_settings = container_attrs.get("NetworkSettings")
    if not isinstance(network_settings, dict):
        return None

    ports = network_settings.get("Ports")
    if not isinstance(ports, dict):
        return None

    bindings = ports.get(OPENCODE_SERVE_CONTAINER_PORT)
    if not isinstance(bindings, list):
        return None

    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        host_port = binding.get("HostPort")
        if host_port is None:
            continue
        host_port_str = str(host_port).strip()
        if not host_port_str:
            continue
        host_ip = _normalize_docker_host_ip(binding.get("HostIp"))
        return f"http://{_format_http_host(host_ip)}:{host_port_str}"

    return None


def _normalize_docker_host_ip(host_ip: object) -> str:
    """Normalize Docker port bindings to a host-reachable HTTP hostname."""
    if not isinstance(host_ip, str) or host_ip in ("", "0.0.0.0", "::"):  # noqa: S104
        return OPENCODE_SERVE_HOST_BIND_IP
    return host_ip


def _format_http_host(host_ip: str) -> str:
    """Bracket IPv6 literals for URLs; leave hostnames/IPv4 unchanged."""
    if ":" in host_ip and not host_ip.startswith("["):
        return f"[{host_ip}]"
    return host_ip
