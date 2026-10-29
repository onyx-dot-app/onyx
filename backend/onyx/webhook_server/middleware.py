"""Tenant resolution for unauthenticated webhook requests."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def add_webhook_tenant_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def set_tenant_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # In cloud a route must resolve the tenant from the body itself: the
        # routing key is in the payload, and reading it here would leave the
        # handler nothing to verify the signature over.
        CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
        return await call_next(request)
