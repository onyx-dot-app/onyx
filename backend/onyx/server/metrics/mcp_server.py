import time
from enum import Enum

from prometheus_client import Counter
from prometheus_client import Histogram

from onyx.server.metrics.mcp_common import MCPToolCallStatus
from onyx.utils.logger import setup_logger

logger = setup_logger()


class MCPAuthResult(str, Enum):
    SUCCESS = "success"
    REJECTED = "rejected"
    ERROR = "error"


class MCPServerToolName(str, Enum):
    SEARCH_INDEXED_DOCUMENTS = "search_indexed_documents"
    SEARCH_WEB = "search_web"
    OPEN_URLS = "open_urls"


# TODO: Add resource metrics when MCP resource usage expands beyond discovery.
UNKNOWN_SOURCE_LABEL = "unknown"

MCP_SERVER_AUTH_TOTAL = Counter(
    "onyx_mcp_server_auth_total",
    "MCP server token verification outcomes",
    ["result"],
)
MCP_SERVER_TOOL_LATENCY = Histogram(
    "onyx_mcp_server_tool_latency_seconds",
    "MCP server tool execution latency",
    ["tool"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
MCP_SERVER_TOOL_TOTAL = Counter(
    "onyx_mcp_server_tool_calls_total",
    "MCP server tool calls",
    ["tool", "status"],
)
MCP_SERVER_SEARCH_RESULTS = Histogram(
    "onyx_mcp_server_search_results",
    "Results returned by MCP server search tools",
    ["tool"],
    buckets=(0, 1, 2, 5, 10, 20, 50),
)
MCP_SERVER_SEARCH_SOURCES = Counter(
    "onyx_mcp_server_search_by_source_total",
    "MCP server document searches by requested source type",
    ["source_type"],
)


def record_mcp_auth_result(result: MCPAuthResult) -> None:
    try:
        MCP_SERVER_AUTH_TOTAL.labels(result=result.value).inc()
    except Exception:
        logger.debug("Failed to record MCP auth metric", exc_info=True)


def record_mcp_server_tool_outcome(
    tool: MCPServerToolName,
    start_time: float,
    status: MCPToolCallStatus,
) -> None:
    try:
        MCP_SERVER_TOOL_LATENCY.labels(tool=tool.value).observe(
            time.monotonic() - start_time
        )
        MCP_SERVER_TOOL_TOTAL.labels(
            tool=tool.value,
            status=status.value,
        ).inc()
    except Exception:
        logger.debug("Failed to record MCP server tool metrics", exc_info=True)


def record_mcp_search_results(
    tool: MCPServerToolName,
    result_count: int,
) -> None:
    try:
        MCP_SERVER_SEARCH_RESULTS.labels(tool=tool.value).observe(result_count)
    except Exception:
        logger.debug("Failed to record MCP search result metric", exc_info=True)


def record_mcp_search_source(source: str) -> None:
    try:
        MCP_SERVER_SEARCH_SOURCES.labels(source_type=source).inc()
    except Exception:
        logger.debug("Failed to record MCP search source metric", exc_info=True)
