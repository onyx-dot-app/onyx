"""Unit tests for the MCP JSON-RPC request classifier.

Pins the fail-closed contract: only recognized protocol plumbing and well-formed
`tools/call` bodies are classifiable; everything else on a matched MCP host is
UNCLASSIFIABLE so the gate denies rather than forwarding with injected creds.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from onyx.sandbox_proxy.mcp_jsonrpc import McpRpcKind, classify_mcp_request


def _body(payload: Any) -> bytes:
    return json.dumps(payload).encode()


def _rpc(method: str, **extra: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, **extra}


@pytest.mark.parametrize(
    "method",
    [
        "initialize",
        "ping",
        "tools/list",
        "resources/list",
        "resources/read",
        "prompts/list",
        "completion/complete",
        "notifications/initialized",
        "notifications/cancelled",
    ],
)
def test_protocol_plumbing_passes(method: str) -> None:
    result = classify_mcp_request("POST", _body(_rpc(method)))
    assert result.kind is McpRpcKind.PLUMBING


@pytest.mark.parametrize("http_method", ["GET", "DELETE"])
def test_bodyless_get_delete_is_plumbing(http_method: str) -> None:
    # The SSE stream (GET) and session teardown (DELETE) carry no invocation.
    assert classify_mcp_request(http_method, None).kind is McpRpcKind.PLUMBING


@pytest.mark.parametrize("http_method", ["HEAD", "PUT", "PATCH", "OPTIONS"])
def test_other_verbs_fail_closed(http_method: str) -> None:
    assert classify_mcp_request(http_method, None).kind is McpRpcKind.UNCLASSIFIABLE


@pytest.mark.parametrize("http_method", ["GET", "DELETE"])
def test_body_bearing_get_delete_fails_closed(http_method: str) -> None:
    # A body on the plumbing verbs could smuggle an invocation past the gate.
    body = _body(_rpc("tools/call", params={"name": "send_email"}))
    assert classify_mcp_request(http_method, body).kind is McpRpcKind.UNCLASSIFIABLE


def test_deeply_nested_body_fails_closed() -> None:
    # json.loads raises RecursionError past the C parser's depth limit; that
    # must classify as UNCLASSIFIABLE, not crash into the gate's fail-open path.
    body = (b"[" * 200_000) + (b"]" * 200_000)
    assert classify_mcp_request("POST", body).kind is McpRpcKind.UNCLASSIFIABLE


def test_tools_call_extracts_tool_name() -> None:
    result = classify_mcp_request(
        "POST",
        _body(_rpc("tools/call", params={"name": "send_email", "arguments": {}})),
    )
    assert result.kind is McpRpcKind.TOOL_CALL
    assert result.tool_names == ("send_email",)


def test_batched_tool_calls_collect_all_names_in_order() -> None:
    result = classify_mcp_request(
        "POST",
        _body(
            [
                _rpc("tools/call", params={"name": "a"}),
                _rpc("tools/call", params={"name": "b"}),
            ]
        ),
    )
    assert result.kind is McpRpcKind.TOOL_CALL
    assert result.tool_names == ("a", "b")


def test_batch_mixing_plumbing_and_tool_call_gates_the_tool() -> None:
    result = classify_mcp_request(
        "POST",
        _body([_rpc("tools/list"), _rpc("tools/call", params={"name": "wipe"})]),
    )
    assert result.kind is McpRpcKind.TOOL_CALL
    assert result.tool_names == ("wipe",)


@pytest.mark.parametrize(
    "payload",
    [
        {"jsonrpc": "2.0", "id": 1, "method": "resources/write"},  # unknown method
        {"jsonrpc": "2.0", "id": 1},  # no method
        {"method": "tools/call", "params": {}},  # tools/call without a name
        {"method": "tools/call", "params": {"name": ""}},  # empty name
        {"method": "tools/call"},  # tools/call without params
        [],  # empty batch
        "not-an-object",  # scalar top level
    ],
)
def test_unclassifiable_bodies_fail_closed(payload: Any) -> None:
    assert (
        classify_mcp_request("POST", _body(payload)).kind is McpRpcKind.UNCLASSIFIABLE
    )


def test_non_json_post_fails_closed() -> None:
    assert classify_mcp_request("POST", b"<html>").kind is McpRpcKind.UNCLASSIFIABLE
    assert classify_mcp_request("POST", None).kind is McpRpcKind.UNCLASSIFIABLE


def test_batch_with_one_unknown_method_fails_closed() -> None:
    result = classify_mcp_request(
        "POST",
        _body([_rpc("tools/call", params={"name": "a"}), _rpc("weird/method")]),
    )
    assert result.kind is McpRpcKind.UNCLASSIFIABLE
