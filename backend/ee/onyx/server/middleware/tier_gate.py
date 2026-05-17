"""Unified tier-gating middleware.

Replaces the old binary `EE_ONLY_PATH_PREFIXES` (license_enforcement)
and ENTERPRISE-only `tier_enforcement` lists with a single declarative
`PATH_PREFIX_MIN_TIER` map.

For every request:
  1. If the path is in `LICENSE_ENFORCEMENT_ALLOWED_PREFIXES`, pass.
  2. Find the longest prefix in `PATH_PREFIX_MIN_TIER` matching the
     request path. No match → pass.
  3. Resolve `current_tier = get_tier()` and compare via `tier_at_least`.
     Pass if sufficient, else respond 402 `FEATURE_NOT_AVAILABLE` with
     the required tier in the payload so the FE can render the right
     upgrade copy.

Wired in `ee/onyx/main.py` for both self-hosted AND multi-tenant. The
orthogonal `license_enforcement` middleware (self-hosted only) still
handles GATED_ACCESS, seat limits, and the billing/auth allowlist.
"""

import asyncio
import logging
from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from fastapi.responses import JSONResponse

from ee.onyx.configs.license_enforcement_config import (
    LICENSE_ENFORCEMENT_ALLOWED_PREFIXES,
)
from ee.onyx.configs.license_enforcement_config import PATH_PREFIX_MIN_TIER
from ee.onyx.utils.tier import get_tier
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.server.settings.models import Tier
from onyx.server.settings.tier_order import tier_at_least
from shared_configs.contextvars import get_current_tenant_id

# Sorted longest-first so `/admin/enterprise-settings/scim` matches
# before `/admin/enterprise-settings`.
_SORTED_GATES: list[tuple[str, Tier]] = sorted(
    PATH_PREFIX_MIN_TIER.items(),
    key=lambda item: len(item[0]),
    reverse=True,
)


def _is_allowed_path(path: str) -> bool:
    return any(
        path.startswith(prefix) for prefix in LICENSE_ENFORCEMENT_ALLOWED_PREFIXES
    )


def _required_tier(path: str) -> Tier | None:
    for prefix, required in _SORTED_GATES:
        if path.startswith(prefix):
            return required
    return None


def add_tier_gate_middleware(app: FastAPI, logger: logging.LoggerAdapter) -> None:
    logger.info("Tier gate middleware registered (entries=%d)", len(_SORTED_GATES))

    @app.middleware("http")
    async def enforce_tier_gate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not _SORTED_GATES:
            return await call_next(request)

        path = request.url.path
        if path.startswith("/api/"):
            path = path[4:]

        if _is_allowed_path(path):
            return await call_next(request)

        required = _required_tier(path)
        if required is None:
            return await call_next(request)

        # `get_tier` is sync: Redis read on every request, plus a blocking
        # CP round-trip on cache miss. Offload to a worker so the event loop
        # is not held while serving other requests.
        tenant_id = get_current_tenant_id()
        current_tier = await asyncio.to_thread(get_tier, tenant_id)
        if tier_at_least(current_tier, required):
            return await call_next(request)

        logger.info(
            "[tier_gate] Blocking %s: required=%s",
            path,
            required.value,
        )
        payload = OnyxErrorCode.FEATURE_NOT_AVAILABLE.detail(
            f"This feature requires the {required.value.title()} plan."
        )
        payload["required_tier"] = required.value
        return JSONResponse(
            status_code=OnyxErrorCode.FEATURE_NOT_AVAILABLE.status_code,
            content=payload,
        )
