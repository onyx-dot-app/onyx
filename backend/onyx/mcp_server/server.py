"""FastMCP server instance for Onyx."""

from fastmcp import FastMCP

from onyx.configs.app_configs import MCP_SERVER_NAME
from onyx.configs.app_configs import MCP_SERVER_VERSION
from onyx.utils.logger import setup_logger

logger = setup_logger()


def create_mcp_server() -> FastMCP:
    """Create FastMCP server instance. Tools/resources added in later phases."""
    logger.info(f"Creating MCP server: {MCP_SERVER_NAME} v{MCP_SERVER_VERSION}")

    mcp = FastMCP(
        name=MCP_SERVER_NAME,
        version=MCP_SERVER_VERSION,
    )

    logger.info("MCP server instance created")
    return mcp


mcp_server = create_mcp_server()
