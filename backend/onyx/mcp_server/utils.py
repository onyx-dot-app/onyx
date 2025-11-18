"""Utility helpers for the Onyx MCP server."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from fastmcp.server.auth.auth import AccessToken

from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


@contextmanager
def tenant_context_from_token(
    access_token: AccessToken | None,
) -> Generator[None, None, None]:
    """Ensure CURRENT_TENANT_ID_CONTEXTVAR is set for the request lifecycle."""

    tenant_id = None
    if access_token:
        tenant_id = access_token.claims.get("tenant_id")

    if not tenant_id:
        if MULTI_TENANT:
            raise RuntimeError(
                "Tenant ID missing from access token in multi-tenant mode"
            )
        tenant_id = POSTGRES_DEFAULT_SCHEMA

    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
