"""PAT authentication middleware for MCP server."""

from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware

from onyx.auth.pat import get_hashed_pat_from_request
from onyx.auth.utils import extract_tenant_from_auth_header
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.pat import fetch_user_for_pat
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Validates PAT from Authorization header and sets tenant context."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        hashed_pat = get_hashed_pat_from_request(request)
        if not hashed_pat:
            logger.warning("MCP request missing PAT")
            raise HTTPException(status_code=401, detail="Missing Personal Access Token")

        async with get_async_session_context_manager() as db_session:
            user = await fetch_user_for_pat(hashed_pat, db_session)

        if user is None:
            logger.warning(f"Invalid PAT: {hashed_pat[:8]}...")
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        if MULTI_TENANT:
            tenant_id = extract_tenant_from_auth_header(request)
            if not tenant_id:
                logger.error("Multi-tenant enabled but no tenant in PAT")
                raise HTTPException(status_code=401, detail="Invalid token format")

            token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
            try:
                logger.debug(f"Authenticated: {user.email}, tenant: {tenant_id}")
                return await call_next(request)
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        else:
            logger.debug(f"Authenticated: {user.email}")
            return await call_next(request)
