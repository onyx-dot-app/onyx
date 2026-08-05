import time

from prometheus_client import Counter, Histogram

from onyx.server.metrics.mcp_common import MCPToolCallStatus
from onyx.utils.logger import setup_logger

logger = setup_logger()

MCP_CLIENT_TOOL_TOTAL = Counter(
    "onyx_mcp_client_tool_calls_total",
    "External MCP tool calls made by Onyx",
    ["server_name", "tool_name", "status"],
)
MCP_CLIENT_TOOL_LATENCY = Histogram(
    "onyx_mcp_client_tool_latency_seconds",
    "External MCP tool call latency",
    ["server_name", "tool_name"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)


def record_mcp_client_tool_outcome(
    server_name: str,
    tool_name: str,
    start_time: float,
    status: MCPToolCallStatus,
) -> None:
    try:
        MCP_CLIENT_TOOL_LATENCY.labels(
            server_name=server_name,
            tool_name=tool_name,
        ).observe(time.monotonic() - start_time)
        MCP_CLIENT_TOOL_TOTAL.labels(
            server_name=server_name,
            tool_name=tool_name,
            status=status.value,
        ).inc()
    except Exception:
        logger.debug("Failed to record MCP client tool metrics", exc_info=True)
