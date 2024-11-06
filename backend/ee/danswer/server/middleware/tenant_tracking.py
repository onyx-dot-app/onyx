import logging
from collections.abc import Awaitable
from collections.abc import Callable

import jwt
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response

from danswer.configs.app_configs import MULTI_TENANT
from danswer.configs.app_configs import SECRET_JWT_KEY
from danswer.db.engine import is_valid_schema_name
from shared_configs.configs import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


def add_tenant_id_middleware(app: FastAPI, logger: logging.LoggerAdapter) -> None:
    @app.middleware("http")
    async def set_tenant_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            logger.info(f"Request route: {request.url.path}")

            if not MULTI_TENANT:
                tenant_id = POSTGRES_DEFAULT_SCHEMA
            else:
                token = request.cookies.get("tenant_details")
                if token:
                    try:
                        payload = jwt.decode(
                            token, SECRET_JWT_KEY, algorithms=["HS256"]
                        )
                        tenant_id = payload.get("tenant_id", POSTGRES_DEFAULT_SCHEMA)
                        if not is_valid_schema_name(tenant_id):
                            raise HTTPException(
                                status_code=400, detail="Invalid tenant ID format"
                            )
                    except jwt.InvalidTokenError:
                        tenant_id = POSTGRES_DEFAULT_SCHEMA
                    except Exception as e:
                        logger.error(
                            f"Unexpected error in set_tenant_id_middleware: {str(e)}"
                        )
                        raise HTTPException(
                            status_code=500, detail="Internal server error"
                        )
                else:
                    tenant_id = POSTGRES_DEFAULT_SCHEMA

            CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
            logger.info(f"Middleware set current_tenant_id to: {tenant_id}")

            response = await call_next(request)
            return response

        except Exception as e:
            logger.error(f"Error in tenant ID middleware: {str(e)}")
            raise
