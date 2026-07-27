import os

from fastmcp import FastMCP

mcp = FastMCP("Onyx stdio test server")


@mcp.tool
def read_configured_value() -> str:
    """Return a value supplied through the stdio process environment."""
    return os.environ["ONYX_STDIO_TEST_VALUE"]


@mcp.tool
def read_unrelated_secret() -> str:
    """Verify that arbitrary API-host environment values are not inherited."""
    return os.environ.get("ONYX_UNRELATED_SECRET", "not-inherited")


if __name__ == "__main__":
    mcp.run(transport="stdio")
