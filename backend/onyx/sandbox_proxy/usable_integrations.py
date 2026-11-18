"""The integrations each sandbox owner can use and the match target of each
enabled integration of a tenant, cached for a short time."""

import threading
import time
from collections.abc import Callable, Hashable
from typing import Any
from uuid import UUID

from cachetools import TTLCache
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import IntegrationKind
from onyx.db.integration import (
    list_enabled_external_apps,
    list_enabled_mcp_server_urls,
    list_enabled_openapi_schemas,
)
from onyx.db.models import ExternalApp
from onyx.integrations.craft import load_usable_integration_ids
from onyx.integrations.models import UsableIntegrationIds
from onyx.sandbox_proxy.resolvers.mcp_matching import (
    IntegrationMatchTarget,
    parse_target,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import openapi_to_url

CACHE_TTL_S = 30.0


class TTLMemo[K: Hashable, V]:
    def __init__(
        self, ttl_s: float, timer: Callable[[], float] = time.monotonic
    ) -> None:
        self._lock = threading.Lock()
        self._cache: TTLCache[K, V] = TTLCache(maxsize=10_000, ttl=ttl_s, timer=timer)

    def get(self, key: K, load: Callable[[], V]) -> V:
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        # Loaded outside the lock so a slow query does not stall other keys; a
        # concurrent duplicate load is harmless.
        value = load()
        with self._lock:
            self._cache[key] = value
        return value


class UsableIntegrations:
    def __init__(
        self, ttl_s: float = CACHE_TTL_S, timer: Callable[[], float] = time.monotonic
    ) -> None:
        self._memo: TTLMemo[tuple[str, UUID], UsableIntegrationIds] = TTLMemo(
            ttl_s, timer
        )
        self._targets: TTLMemo[str, tuple[IntegrationMatchTarget, ...]] = TTLMemo(
            ttl_s, timer
        )

    def get(self, tenant_id: str, user_id: UUID) -> UsableIntegrationIds:
        return self._memo.get(
            (tenant_id, user_id), lambda: self._load(tenant_id, user_id)
        )

    def targets(self, tenant_id: str) -> tuple[IntegrationMatchTarget, ...]:
        """Of each enabled integration of the tenant, for all users: a host
        that an integration claims never forwards bare."""
        return self._targets.get(tenant_id, lambda: self._load_targets(tenant_id))

    def _load(self, tenant_id: str, user_id: UUID) -> UsableIntegrationIds:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            return load_usable_integration_ids(db, user_id)

    def _load_targets(self, tenant_id: str) -> tuple[IntegrationMatchTarget, ...]:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            return load_match_targets(db)


def load_match_targets(
    db_session: Session, only_integration_id: int | None = None
) -> tuple[IntegrationMatchTarget, ...]:
    """One query for each kind table, for each enabled integration or for only
    ``only_integration_id``. An integration with an unusable URL matches
    nothing; one with settings or a URL that do not parse gets a
    ``load_error``."""
    targets: list[IntegrationMatchTarget] = []
    for integration_id, server_url in list_enabled_mcp_server_urls(
        db_session, only_integration_id
    ):
        target = mcp_match_target(integration_id, server_url)
        if target is not None:
            targets.append(target)
    for integration_id, schema in list_enabled_openapi_schemas(
        db_session, only_integration_id
    ):
        target = openapi_match_target(integration_id, schema)
        if target is not None:
            targets.append(target)
    targets.extend(
        app_match_target(integration_id, app)
        for integration_id, app in list_enabled_external_apps(
            db_session, only_integration_id
        )
    )
    return tuple(targets)


def mcp_match_target(
    integration_id: int, server_url: str
) -> IntegrationMatchTarget | None:
    try:
        endpoint = parse_target(integration_id, server_url)
    except ValueError as e:
        return _broken_target(integration_id, IntegrationKind.MCP, _bad_url(e))
    if endpoint is None:
        return None
    return IntegrationMatchTarget(
        integration_id=integration_id, kind=IntegrationKind.MCP, endpoint=endpoint
    )


def app_match_target(integration_id: int, app: ExternalApp) -> IntegrationMatchTarget:
    try:
        regexes = tuple(app.upstream_url_regexes)
    except ValueError as e:
        return _broken_api_target(integration_id, str(e))
    return IntegrationMatchTarget(
        integration_id=integration_id,
        kind=IntegrationKind.API,
        app_type=app.app_type,
        url_regexes=regexes,
    )


def openapi_match_target(
    integration_id: int, schema: dict[str, Any] | None
) -> IntegrationMatchTarget | None:
    if schema is None:
        return _broken_api_target(
            integration_id, f"Integration {integration_id} has no API settings."
        )
    try:
        base_url = openapi_to_url(schema)
    except ValueError as e:
        return _broken_api_target(integration_id, str(e))
    try:
        endpoint = parse_target(integration_id, base_url)
    except ValueError as e:
        return _broken_api_target(integration_id, _bad_url(e))
    if endpoint is None:
        return None
    return IntegrationMatchTarget(
        integration_id=integration_id, kind=IntegrationKind.API, endpoint=endpoint
    )


def _bad_url(error: ValueError) -> str:
    return f"The integration URL is not valid: {error}"


def _broken_api_target(integration_id: int, error: str) -> IntegrationMatchTarget:
    return _broken_target(integration_id, IntegrationKind.API, error)


def _broken_target(
    integration_id: int, kind: IntegrationKind, error: str
) -> IntegrationMatchTarget:
    return IntegrationMatchTarget(
        integration_id=integration_id, kind=kind, load_error=error
    )
