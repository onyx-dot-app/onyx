"""The webhook server: one FastAPI app that receives connector events.

Separate from the api_server because the endpoint is unauthenticated, and
because the api_server resolves a tenant from a session, a bearer token or
the OAuth provider — none of which a provider's POST carries.

Single tenant only for now: `webhook_server_main` refuses to start under
MULTI_TENANT, because nothing here resolves a tenant. Supporting cloud
means reading it from the payload, where the routing key lives.

A source becomes reachable by registering a `WebhookSourceSpec`; no
source has registered one yet, so the app serves only `/health` and
`/metrics` today.
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
from onyx.webhook_server.routes import build_webhook_router


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

    # One route per source that registered a spec. A source with no
    # active connector still has its route; the handler turns the
    # delivery away.
    app.include_router(build_webhook_router())

    expose_prometheus_metrics(app, create_prometheus_instrumentator())
    return app


webhook_app = create_webhook_app()
