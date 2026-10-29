"""Tenant resolution for unauthenticated webhook requests.

The api_server resolves a tenant from a session cookie, a bearer token, an
anonymous JWT or the OAuth provider. A provider's POST carries none of those,
so anything this app runs needs a schema set for it.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def add_webhook_tenant_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def set_tenant_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Single tenant has one schema, and in cloud a route has to resolve
        # the tenant from the request body itself: the routing key is in the
        # payload, and a middleware that read the body would leave the
        # handler nothing to verify the signature over. Until a route does
        # that, every request runs against the default schema.
        CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
        return await call_next(request)
