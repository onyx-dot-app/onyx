"""FastMCP server instance for Onyx."""

from fastmcp import FastMCP

from onyx.configs.app_configs import MCP_SERVER_NAME
from onyx.configs.app_configs import MCP_SERVER_VERSION
from onyx.mcp_server.auth import OnyxPATVerifier
from onyx.utils.logger import setup_logger

logger = setup_logger()


def create_mcp_server() -> FastMCP:
    """Create FastMCP server instance with PAT authentication."""
    logger.info(f"Creating MCP server: {MCP_SERVER_NAME} v{MCP_SERVER_VERSION}")

    # Create FastMCP with PAT authentication
    mcp = FastMCP(
        name=MCP_SERVER_NAME,
        version=MCP_SERVER_VERSION,
        auth=OnyxPATVerifier(),  # Use custom PAT verifier
    )

    logger.info("MCP server instance created")
    return mcp


mcp_server = create_mcp_server()
