import logging
from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response

from ee.onyx.auth.users import decode_anonymous_user_jwt_token
from onyx.auth.api_key import extract_tenant_from_api_key_header
from onyx.configs.constants import ANONYMOUS_USER_COOKIE_NAME
from onyx.configs.constants import TENANT_ID_COOKIE_NAME
from onyx.db.engine.sql_engine import is_valid_schema_name
from onyx.redis.redis_pool import retrieve_auth_token_data_from_redis
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def add_api_server_tenant_id_middleware(
    app: FastAPI, logger: logging.LoggerAdapter
) -> None:
    @app.middleware("http")
    async def set_tenant_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Extracts the tenant id from multiple locations and sets the context var.

        This is very specific to the api server and probably not something you'd want
        to use elsewhere.
        """
        try:
            if MULTI_TENANT:
                tenant_id = await _get_tenant_id_from_request(request, logger)
            else:
                tenant_id = POSTGRES_DEFAULT_SCHEMA

            CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
            return await call_next(request)

        except Exception as e:
            logger.exception(f"Error in tenant ID middleware: {str(e)}")
            raise


async def _get_tenant_id_from_request(
    request: Request, logger: logging.LoggerAdapter
) -> str:
    """
    Attempt to extract tenant_id from:
    1) The API key header
    2) The Redis-based token (stored in Cookie: fastapiusersauth)
    3) The anonymous user cookie
    Fallback: POSTGRES_DEFAULT_SCHEMA
    """
    # Check for API key
    tenant_id = extract_tenant_from_api_key_header(request)
    if tenant_id is not None:
        return tenant_id

    try:
        # Look up token data in Redis

        token_data = await retrieve_auth_token_data_from_redis(request)

        if token_data:
            tenant_id_from_payload = token_data.get(
                "tenant_id", POSTGRES_DEFAULT_SCHEMA
            )

            tenant_id = (
                str(tenant_id_from_payload)
                if tenant_id_from_payload is not None
                else None
            )

            if tenant_id and not is_valid_schema_name(tenant_id):
                raise HTTPException(status_code=400, detail="Invalid tenant ID format")

        # Check for anonymous user cookie
        anonymous_user_cookie = request.cookies.get(ANONYMOUS_USER_COOKIE_NAME)
        if anonymous_user_cookie:
            try:
                anonymous_user_data = decode_anonymous_user_jwt_token(
                    anonymous_user_cookie
                )
                tenant_id = anonymous_user_data.get(
                    "tenant_id", POSTGRES_DEFAULT_SCHEMA
                )

                if not tenant_id or not is_valid_schema_name(tenant_id):
                    raise HTTPException(
                        status_code=400, detail="Invalid tenant ID format"
                    )

                return tenant_id

            except Exception as e:
                logger.error(f"Error decoding anonymous user cookie: {str(e)}")
                # Continue and attempt to authenticate

        logger.debug(
            "Token data not found or expired in Redis, defaulting to POSTGRES_DEFAULT_SCHEMA"
        )

        # Return POSTGRES_DEFAULT_SCHEMA, so non-authenticated requests are sent to the default schema
        # The CURRENT_TENANT_ID_CONTEXTVAR is initialized with POSTGRES_DEFAULT_SCHEMA,
        # so we maintain consistency by returning it here when no valid tenant is found.
        return POSTGRES_DEFAULT_SCHEMA

    except Exception as e:
        logger.error(f"Unexpected error in _get_tenant_id_from_request: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

    finally:
        if tenant_id:
            return tenant_id

        # As a final step, check for explicit tenant_id cookie
        tenant_id_cookie = request.cookies.get(TENANT_ID_COOKIE_NAME)
        if tenant_id_cookie and is_valid_schema_name(tenant_id_cookie):
            return tenant_id_cookie

        # If we've reached this point, return the default schema
        return POSTGRES_DEFAULT_SCHEMA
