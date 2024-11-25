import logging
from collections.abc import Awaitable
from collections.abc import Callable

import jwt
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response

from danswer.auth.api_key import extract_tenant_from_api_key_header
from danswer.configs.app_configs import USER_AUTH_SECRET
from danswer.db.engine import is_valid_schema_name
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def add_tenant_id_middleware(app: FastAPI, logger: logging.LoggerAdapter) -> None:
    @app.middleware("http")
    async def set_tenant_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            tenant_id = (
                _get_tenant_id_from_request(request, logger)
                if MULTI_TENANT
                else POSTGRES_DEFAULT_SCHEMA
            )
            CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
            return await call_next(request)

        except Exception as e:
            logger.error(f"Error in tenant ID middleware: {str(e)}")
            raise


def _get_tenant_id_from_request(request: Request, logger: logging.LoggerAdapter) -> str:
    # First check for API key
    tenant_id = extract_tenant_from_api_key_header(request)
    if tenant_id is not None:
        return tenant_id

    # Check for cookie-based auth
    token = request.cookies.get("fastapiusersauth")
    if not token:
        return POSTGRES_DEFAULT_SCHEMA

    try:
        payload = jwt.decode(
            token,
            USER_AUTH_SECRET,
            audience=["fastapi-users:auth"],
            algorithms=["HS256"],
        )
        tenant_id_from_payload = payload.get("tenant_id", POSTGRES_DEFAULT_SCHEMA)

        # Since payload.get() can return None, ensure we have a string
        tenant_id = (
            str(tenant_id_from_payload)
            if tenant_id_from_payload is not None
            else POSTGRES_DEFAULT_SCHEMA
        )

        if not is_valid_schema_name(tenant_id):
            raise HTTPException(status_code=400, detail="Invalid tenant ID format")

        return tenant_id

    except jwt.InvalidTokenError:
        return POSTGRES_DEFAULT_SCHEMA

    except Exception as e:
        logger.error(f"Unexpected error in set_tenant_id_middleware: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
