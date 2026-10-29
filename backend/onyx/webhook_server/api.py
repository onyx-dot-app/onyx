"""The webhook server: one FastAPI app that receives connector events.

Separate from the api_server because the endpoint is unauthenticated, and
because the api_server resolves a tenant from a session, a bearer token or
the OAuth provider — none of which a provider's POST carries.

It serves no event route yet; a source adds one in a later change.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import RequestResponseEndpoint

from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.metrics.prometheus_setup import (
    create_prometheus_instrumentator,
    expose_prometheus_metrics,
)
from onyx.utils.variable_functionality import set_is_ee_if_available
from onyx.webhook_server.middleware import add_webhook_tenant_middleware


def create_webhook_app() -> FastAPI:
    set_is_ee_if_available()

    app = FastAPI(
        title="Onyx Webhook Server",
        description="Receives connector events from event-based sources",
        # No browser reaches this app, so interactive docs only widen the surface.
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    register_onyx_exception_handlers(app)

    @app.middleware("http")
    async def health_check(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path.rstrip("/") == "/health":
            return JSONResponse({"status": "healthy", "service": "webhook_server"})
        return await call_next(request)

    add_webhook_tenant_middleware(app)

    expose_prometheus_metrics(app, create_prometheus_instrumentator())
    return app


webhook_app = create_webhook_app()
