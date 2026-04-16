"""Entry point for MCP server - HTTP POST transport with API key auth."""

import uvicorn

from onyx.configs.app_configs import MCP_SERVER_ENABLED
from onyx.configs.app_configs import MCP_SERVER_HOST
from onyx.configs.app_configs import MCP_SERVER_PORT
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import set_is_ee_based_on_env_variable

logger = setup_logger()


def main() -> None:
    """Run the MCP server."""
    if not MCP_SERVER_ENABLED:
        logger.info("MCP server is disabled (MCP_SERVER_ENABLED=false)")
        return

    set_is_ee_based_on_env_variable()
    logger.info(f"Starting MCP server on {MCP_SERVER_HOST}:{MCP_SERVER_PORT}")

    from onyx.mcp_server.api import mcp_app

    uvicorn.run(
        mcp_app,
        host=MCP_SERVER_HOST,
        port=MCP_SERVER_PORT,
        log_config=None,
    )


if __name__ == "__main__":
    main()
