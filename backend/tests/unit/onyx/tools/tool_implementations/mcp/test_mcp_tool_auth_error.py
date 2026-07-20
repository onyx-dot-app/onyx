"""Tests that MCPTool.run() flags auth failures on both the emitted
CustomToolDelta and the returned CustomToolCallSummary.

Two auth-error paths exist in run():
  1. Never-authenticated (pre-call): the server requires auth but no
     credentials/headers are configured -> status_code 401.
  2. Auth failure at call time: the underlying MCP call raises an exception
     whose message matches an auth indicator -> 401 (or 403 for forbidden).

A non-auth failure (e.g. "connection reset") must NOT be tagged, so the chat
UI doesn't falsely prompt re-auth.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.models import CustomToolCallSummary
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool


def _capturing_emitter() -> MagicMock:
    """A MagicMock emitter whose emit() records every Packet on .packets.

    MCPTool only calls emitter.emit(); a MagicMock keeps ty happy (Emitter is
    untyped past the constructor) while letting us inspect what was emitted.
    """
    emitter = MagicMock()
    packets: list[Packet] = []
    emitter.packets = packets
    emitter.emit.side_effect = packets.append
    return emitter


def _placement() -> Placement:
    return Placement(turn_index=0)


def _captured_deltas(emitter: MagicMock) -> list[CustomToolDelta]:
    return [p.obj for p in emitter.packets if isinstance(p.obj, CustomToolDelta)]


def _make_tool(
    emitter: MagicMock,
    auth_type: MCPAuthenticationType,
) -> MCPTool:
    mcp_server = MagicMock()
    mcp_server.name = "test-mcp"
    mcp_server.server_url = "https://mcp.example.com/mcp"
    mcp_server.auth_type = auth_type
    mcp_server.transport = MCPTransport.STREAMABLE_HTTP
    return MCPTool(
        tool_id=1,
        emitter=emitter,
        mcp_server=mcp_server,
        tool_name="do_thing",
        tool_description="Does a thing",
        tool_definition={"type": "object", "properties": {}},
        connection_config=None,
    )


class TestNeverAuthenticatedPath:
    def test_requires_auth_without_credentials_is_tagged_401(self) -> None:
        # API_TOKEN auth required, but no connection_config / headers / token ->
        # has_auth_config is False -> pre-call auth-error branch.
        emitter = _capturing_emitter()
        tool = _make_tool(emitter, MCPAuthenticationType.API_TOKEN)

        response = tool.run(_placement())

        deltas = _captured_deltas(emitter)
        assert len(deltas) == 1
        assert deltas[0].error is not None
        assert deltas[0].error.is_auth_error is True
        assert deltas[0].error.status_code == 401

        summary = response.rich_response
        assert isinstance(summary, CustomToolCallSummary)
        assert summary.error is not None
        assert summary.error.is_auth_error is True
        assert summary.error.status_code == 401


class TestCallTimeAuthFailurePath:
    def test_401_exception_is_tagged_401(self) -> None:
        # NONE auth -> skips the pre-call check and reaches call_mcp_tool, which
        # we make raise an auth-indicating error.
        emitter = _capturing_emitter()
        tool = _make_tool(emitter, MCPAuthenticationType.NONE)

        with patch(
            "onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool",
            side_effect=Exception("HTTP 401 Unauthorized"),
        ):
            response = tool.run(_placement())

        deltas = _captured_deltas(emitter)
        assert len(deltas) == 1
        assert deltas[0].error is not None
        assert deltas[0].error.is_auth_error is True
        assert deltas[0].error.status_code == 401

        summary = response.rich_response
        assert isinstance(summary, CustomToolCallSummary)
        assert summary.error is not None
        assert summary.error.is_auth_error is True
        assert summary.error.status_code == 401

    def test_403_forbidden_exception_is_tagged_403(self) -> None:
        emitter = _capturing_emitter()
        tool = _make_tool(emitter, MCPAuthenticationType.NONE)

        with patch(
            "onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool",
            side_effect=Exception("HTTP 403 Forbidden"),
        ):
            response = tool.run(_placement())

        deltas = _captured_deltas(emitter)
        assert deltas[0].error is not None
        assert deltas[0].error.is_auth_error is True
        assert deltas[0].error.status_code == 403

        summary = response.rich_response
        assert isinstance(summary, CustomToolCallSummary)
        assert summary.error is not None
        assert summary.error.status_code == 403

    def test_non_auth_exception_is_not_tagged(self) -> None:
        # Control: a generic failure must not be mistaken for an auth error.
        emitter = _capturing_emitter()
        tool = _make_tool(emitter, MCPAuthenticationType.NONE)

        with patch(
            "onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool",
            side_effect=Exception("connection reset by peer"),
        ):
            response = tool.run(_placement())

        deltas = _captured_deltas(emitter)
        assert len(deltas) == 1
        assert deltas[0].error is None

        summary = response.rich_response
        assert isinstance(summary, CustomToolCallSummary)
        assert summary.error is None


if __name__ == "__main__":
    pytest.main([__file__, "-xv"])
