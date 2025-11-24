"""MCP server with FastAPI wrapper."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from fastmcp import FastMCP
from starlette.middleware.base import RequestResponseEndpoint

from onyx.configs.app_configs import MCP_SERVER_CORS_ORIGINS
from onyx.mcp_server.auth import OnyxTokenVerifier
from onyx.mcp_server.utils import shutdown_http_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

logger.info("Creating Onyx MCP Server...")

mcp_server = FastMCP(
    name="Onyx MCP Server",
    version="1.0.0",
    auth=OnyxTokenVerifier(),
)

# Import tools and resources AFTER mcp_server is created to avoid circular imports
# Components register themselves via decorators on the shared mcp_server instance
from onyx.mcp_server.tools import search  # noqa: E402, F401
from onyx.mcp_server.resources import indexed_sources  # noqa: E402, F401

logger.info("MCP server instance created")


def create_mcp_fastapi_app() -> FastAPI:
    """Create FastAPI app wrapping MCP server with auth and shared client lifecycle."""
    mcp_asgi_app = mcp_server.http_app(path="/")

    @asynccontextmanager
    async def combined_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Initializes MCP session manager."""
        logger.info("MCP server starting up")

        try:
            async with mcp_asgi_app.lifespan(app):
                yield
        finally:
            logger.info("MCP server shutting down")
            await shutdown_http_client()

    app = FastAPI(
        title="Onyx MCP Server",
        description="HTTP POST transport with bearer auth delegated to API /me",
        version="1.0.0",
        lifespan=combined_lifespan,
    )

    # Public health check endpoint (bypasses MCP auth)
    @app.middleware("http")
    async def health_check(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path.rstrip("/") == "/health":
            return JSONResponse({"status": "healthy", "service": "mcp_server"})
        return await call_next(request)

    # Authentication is handled by FastMCP's OnyxTokenVerifier (see auth.py)

    if MCP_SERVER_CORS_ORIGINS:
        logger.info(f"CORS origins: {MCP_SERVER_CORS_ORIGINS}")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=MCP_SERVER_CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.mount("/", mcp_asgi_app)

    return app


mcp_app = create_mcp_fastapi_app()
