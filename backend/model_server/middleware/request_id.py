# import logging
# from collections.abc import Awaitable
# from collections.abc import Callable
# import uuid
# from fastapi import FastAPI
# from fastapi import HTTPException
# from fastapi import Request
# from fastapi import Response
# from ee.onyx.auth.users import decode_anonymous_user_jwt_token
# from ee.onyx.configs.app_configs import ANONYMOUS_USER_COOKIE_NAME
# from onyx.auth.api_key import extract_tenant_from_api_key_header
# from onyx.db.engine import is_valid_schema_name
# from onyx.redis.redis_pool import retrieve_auth_token_data_from_redis
# from shared_configs.configs import MULTI_TENANT
# from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
# from shared_configs.contextvars import CURRENT_INDEXING_REQUEST_ID_CONTEXTVAR, CURRENT_TENANT_ID_CONTEXTVAR
# def add_request_id_middleware(app: FastAPI, logger: logging.LoggerAdapter) -> None:
#     @app.middleware("http")
#     async def set_request_id_middleware(request: Request, call_next):
#         # Get the request ID from headers or generate a new one
#         request_id = request.headers.get("X-Onyx-Indexing-Request-ID", str(uuid.uuid4()))
#         CURRENT_INDEXING_REQUEST_ID_CONTEXTVAR.set(request_id) # Set the ContextVar
#         response = await call_next(request)
#         return response
