"""Helpers for normalizing ingress paths to application route paths."""

from onyx.configs.app_configs import APP_API_PREFIX


def strip_api_prefix(path: str) -> str:
    """Remove the configured API prefix from an incoming request path.

    When no API prefix is configured, retain the legacy ``/api`` fallback for
    deployments whose reverse proxy forwards that prefix to the API server.
    """
    configured_prefix = f"/{APP_API_PREFIX.strip('/')}" if APP_API_PREFIX else "/api"
    if path == configured_prefix:
        return "/"

    prefix_with_separator = f"{configured_prefix}/"
    if path.startswith(prefix_with_separator):
        return path[len(configured_prefix) :]

    return path
