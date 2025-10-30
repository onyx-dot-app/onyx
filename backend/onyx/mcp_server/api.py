"""FastAPI wrapper for MCP server."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from onyx.configs.app_configs import MCP_SERVER_CORS_ORIGINS
from onyx.configs.constants import POSTGRES_WEB_APP_NAME
from onyx.db.engine.sql_engine import SqlEngine
from onyx.mcp_server.middleware import MCPAuthMiddleware
from onyx.mcp_server.server import mcp_server
from onyx.utils.logger import setup_logger

logger = setup_logger()


def create_mcp_fastapi_app() -> FastAPI:
    """Create FastAPI app wrapping MCP server with auth and DB initialization."""
    mcp_asgi_app = mcp_server.http_app(path="/")

    @asynccontextmanager
    async def combined_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Initializes DB pool and MCP session manager."""
        logger.info("MCP server starting up")

        SqlEngine.set_app_name(f"{POSTGRES_WEB_APP_NAME}_mcp_server")
        SqlEngine.init_engine(
            pool_size=2,  # Phase 1: minimal (only API key validation)
            max_overflow=3,  # Can grow to 5 connections under load
        )
        logger.info("Database initialized")

        async with mcp_asgi_app.lifespan(app):
            yield

        logger.info("MCP server shutting down")
        SqlEngine.reset_engine()

    app = FastAPI(
        title="Onyx MCP Server",
        description="HTTP POST transport with API key auth",
        version="1.0.0",
        lifespan=combined_lifespan,
    )

    @app.get("/health")
    async def health_check() -> JSONResponse:
        return JSONResponse({"status": "healthy", "service": "mcp_server"})

    app.add_middleware(MCPAuthMiddleware)

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
