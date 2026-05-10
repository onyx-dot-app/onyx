"""Cloud-only tier gating middleware. Counterpart to license_enforcement."""

import logging
from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from fastapi.responses import JSONResponse

from ee.onyx.configs.tier_enforcement_config import ENTERPRISE_ONLY_PATH_PREFIXES
from ee.onyx.utils.tier import get_tier
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.server.settings.models import Tier


def _is_enterprise_only_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in ENTERPRISE_ONLY_PATH_PREFIXES)


def add_tier_enforcement_middleware(
    app: FastAPI, logger: logging.LoggerAdapter
) -> None:
    logger.info("Tier enforcement middleware registered")

    @app.middleware("http")
    async def enforce_tier(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Fast-path: skip get_tier() entirely when nothing is gated.
        if not ENTERPRISE_ONLY_PATH_PREFIXES:
            return await call_next(request)

        path = request.url.path
        if path.startswith("/api"):
            path = path[4:]

        if not _is_enterprise_only_path(path):
            return await call_next(request)

        if get_tier() == Tier.ENTERPRISE:
            return await call_next(request)

        logger.info(
            "[tier_enforcement] Blocking request below ENTERPRISE tier: %s", path
        )
        return JSONResponse(
            status_code=OnyxErrorCode.FEATURE_NOT_AVAILABLE.status_code,
            content=OnyxErrorCode.FEATURE_NOT_AVAILABLE.detail(
                "This feature requires the Enterprise plan."
            ),
        )
