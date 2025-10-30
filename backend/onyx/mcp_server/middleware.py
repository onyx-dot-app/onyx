"""API key authentication middleware for MCP server."""

from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware

from onyx.auth.api_key import extract_tenant_from_api_key_header
from onyx.auth.api_key import get_hashed_api_key_from_request
from onyx.db.api_key import fetch_user_for_api_key
from onyx.db.engine.sql_engine import get_async_session
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Validates API key from Authorization header and sets tenant context."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        hashed_api_key = get_hashed_api_key_from_request(request)
        if not hashed_api_key:
            logger.warning("MCP request missing API key")
            raise HTTPException(status_code=401, detail="Missing API key")

        async for db_session in get_async_session():
            user = await fetch_user_for_api_key(hashed_api_key, db_session)
            break

        if user is None:
            logger.warning(f"Invalid API key: {hashed_api_key[:8]}...")
            raise HTTPException(status_code=401, detail="Invalid API key")

        if MULTI_TENANT:
            tenant_id = extract_tenant_from_api_key_header(request)
            if not tenant_id:
                logger.error("Multi-tenant enabled but no tenant in API key")
                raise HTTPException(status_code=401, detail="Invalid API key format")

            token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
            try:
                logger.debug(f"Authenticated: {user.email}, tenant: {tenant_id}")
                return await call_next(request)
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        else:
            logger.debug(f"Authenticated: {user.email}")
            return await call_next(request)
