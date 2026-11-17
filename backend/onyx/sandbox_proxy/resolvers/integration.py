"""Integration credential resolver.

Injects the credential of the integration that the request evaluator matched:
``resolve_call_credentials`` resolves the connection of the sandbox owner (or
of the organization), refreshes a token that expires soon and renders the
header template. It also claims each request to the host of an enabled MCP
integration that the evaluator did not match, and blocks it: a request outside
every server URL, to a server the user cannot use, or with no gate verdict
never forwards. ``claims()`` serves host ownership from a short-TTL per-tenant
cache, the one deliberate DB touch on the claims path.
"""

from __future__ import annotations

import threading
from uuid import UUID

from cachetools import TTLCache
from mitmproxy import http

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.integration import get_integration_by_id, list_enabled_mcp_server_urls
from onyx.db.users import fetch_user_by_id
from onyx.external_apps.matching.engine import GatedTarget
from onyx.integrations.call_credentials import resolve_call_credentials
from onyx.integrations.connections import ConnectionProblem
from onyx.integrations.craft import list_visible_integrations
from onyx.sandbox_proxy.credential_injection import (
    CredentialResolver,
    CredentialUnavailableError,
)
from onyx.sandbox_proxy.logging_utils import short_log_id
from onyx.sandbox_proxy.mcp_jsonrpc import classify_mcp_request
from onyx.sandbox_proxy.models import InjectionContext, McpRpcKind
from onyx.sandbox_proxy.resolvers.mcp_matching import (
    CraftMCPTarget,
    host_targets,
    normalized_request_path,
    parse_target,
)
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox
from onyx.utils.credential_audit import emit_credential_access
from onyx.utils.logger import setup_logger

logger = setup_logger()

_TARGET_CACHE_TTL_S = 30.0


class IntegrationResolver(CredentialResolver):
    """Injects the credential of the matched integration."""

    def __init__(self, cache_ttl_s: float = _TARGET_CACHE_TTL_S) -> None:
        self._cache_lock = threading.Lock()
        # MCP host ownership (claims): user-agnostic, so a claimed host never
        # forwards bare for a user who cannot use the server.
        self._targets_by_tenant: TTLCache[str, tuple[CraftMCPTarget, ...]] = TTLCache(
            maxsize=10_000, ttl=cache_ttl_s
        )
        # The integrations of the plugins each user can see.
        self._accessible_ids_by_user: TTLCache[tuple[str, UUID], frozenset[int]] = (
            TTLCache(maxsize=10_000, ttl=cache_ttl_s)
        )

    def allows_destination(
        self, sandbox: ResolvedSandbox, scheme: str, host: str, port: int
    ) -> bool:
        """Allow an internal origin only for an MCP integration of a plugin
        that the user can see. A scheduled run can use a task plugin that the
        user turned off; the gate matches each request."""
        if scheme not in {"http", "https"}:
            return False
        runnable = self._accessible_ids(sandbox.tenant_id, sandbox.user_id)
        return bool(
            host_targets(
                tuple(
                    target
                    for target in self._targets(sandbox.tenant_id)
                    if target.server_id in runnable
                ),
                scheme,
                host,
                port,
            )
        )

    def claims(self, request: http.Request, ctx: InjectionContext) -> bool:
        if ctx.target is not None:
            return True
        return bool(
            host_targets(
                self._targets(ctx.sandbox.tenant_id),
                request.scheme,
                request.host,
                request.port,
            )
        )

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        target = ctx.target
        if target is not None:
            # Inject for the exact integration the gate evaluated, never a
            # re-match against the cached targets.
            return self._resolve_for_target(target, ctx.sandbox)
        classification = classify_mcp_request(request)
        if classification.kind is not McpRpcKind.PLUMBING:
            raise CredentialUnavailableError(
                f"non-plumbing MCP request on {request.host} reached credential "
                "injection without a gate verdict; blocked",
                sandbox_detail=(
                    "This MCP request could not be verified by the approval "
                    "gate. Retry the tool call."
                ),
            )
        path = normalized_request_path(request.path or "")
        raise CredentialUnavailableError(
            f"request path {path!r} on MCP host {request.host} matches no "
            "MCP server that the user can use",
            sandbox_detail=(
                "This host belongs to an MCP server configured in Onyx, but "
                "the request is outside an MCP endpoint that you can use, so "
                "it was blocked. Turn on a plugin that holds the server, or "
                "use the configured MCP endpoint."
            ),
        )

    def _resolve_for_target(
        self, target: GatedTarget, sandbox: ResolvedSandbox
    ) -> dict[str, str]:
        with get_session_with_tenant(tenant_id=sandbox.tenant_id) as db:
            integration = get_integration_by_id(target.integration_id, db)
            if integration is None or not integration.enabled:
                raise CredentialUnavailableError(
                    f"integration {target.integration_id} is no longer available",
                    sandbox_detail=f'"{target.app_name}" is no longer available.',
                )
            user = fetch_user_by_id(db, sandbox.user_id)
            if user is None:
                raise CredentialUnavailableError(
                    f"sandbox user {short_log_id(sandbox.user_id)} not found"
                )
            credentials = resolve_call_credentials(integration, user, db)
            if isinstance(credentials, ConnectionProblem):
                raise CredentialUnavailableError(
                    f"integration {integration.id}: {credentials.code.value}",
                    sandbox_detail=credentials.reason,
                )
            if credentials.headers:
                emit_credential_access(
                    credential_type="integration",
                    provider=integration.name,
                    row_id=integration.id,
                    user_id=str(sandbox.user_id),
                    auth_type=(
                        integration.auth_method.value
                        if integration.auth_method is not None
                        else None
                    ),
                )
            return credentials.headers

    def _targets(self, tenant_id: str) -> tuple[CraftMCPTarget, ...]:
        with self._cache_lock:
            cached = self._targets_by_tenant.get(tenant_id)
        if cached is not None:
            return cached
        # Loaded outside the lock so a slow query can't stall other tenants'
        # claims; a concurrent duplicate load is harmless.
        targets = self._load_targets(tenant_id)
        with self._cache_lock:
            self._targets_by_tenant[tenant_id] = targets
        return targets

    def _load_targets(self, tenant_id: str) -> tuple[CraftMCPTarget, ...]:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            parsed = [
                parse_target(integration_id, server_url)
                for integration_id, server_url in list_enabled_mcp_server_urls(db)
            ]
        return tuple(target for target in parsed if target is not None)

    def _accessible_ids(self, tenant_id: str, user_id: UUID) -> frozenset[int]:
        key = (tenant_id, user_id)
        with self._cache_lock:
            cached = self._accessible_ids_by_user.get(key)
        if cached is not None:
            return cached
        ids = self._load_accessible_ids(tenant_id, user_id)
        with self._cache_lock:
            self._accessible_ids_by_user[key] = ids
        return ids

    def _load_accessible_ids(self, tenant_id: str, user_id: UUID) -> frozenset[int]:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            return frozenset(
                integration.id for integration in list_visible_integrations(db, user_id)
            )
