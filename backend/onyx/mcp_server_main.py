"""Entry point for MCP server - HTTP POST transport with API key auth."""

import uvicorn

from onyx.configs.app_configs import MCP_SERVER_ENABLED
from onyx.configs.app_configs import MCP_SERVER_PORT
from onyx.utils.logger import setup_logger

logger = setup_logger()


def main() -> None:
    """Run the MCP server."""
    if not MCP_SERVER_ENABLED:
        logger.info("MCP server is disabled (MCP_SERVER_ENABLED=false)")
        return

    logger.info(f"Starting MCP server on 0.0.0.0:{MCP_SERVER_PORT}")

    from onyx.mcp_server.api import mcp_app

    uvicorn.run(
        mcp_app,
        host="0.0.0.0",
        port=MCP_SERVER_PORT,
        log_config=None,
    )


if __name__ == "__main__":
    main()
