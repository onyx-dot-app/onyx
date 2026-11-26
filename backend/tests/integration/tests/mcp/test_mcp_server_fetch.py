"""Integration tests for the MCP search/fetch tools and their protocol contract."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from mcp import ClientSession
from mcp.types import CallToolResult, TextContent

from onyx.db.enums import AccessType
from tests.integration.common_utils.constants import MCP_SERVER_URL
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.mcp.test_mcp_server_search import (
    _auth_headers,
    _run_with_mcp_session,
)

READ_ONLY_TOOLS = {
    "search",
    "fetch",
    "search_indexed_documents",
    "query_metadata",
    "search_web",
    "open_urls",
}


def _call(
    headers: dict[str, str], tool: str, arguments: dict[str, Any]
) -> CallToolResult:
    async def _action(session: ClientSession) -> CallToolResult:
        await session.initialize()
        return await session.call_tool(tool, arguments)

    return _run_with_mcp_session(headers, _action)


def _text_payload(result: CallToolResult) -> dict[str, Any]:
    (block,) = result.content
    assert isinstance(block, TextContent)
    payload = json.loads(block.text)
    assert isinstance(payload, dict)
    return payload


def _search_ids(headers: dict[str, str], query: str) -> list[dict[str, Any]]:
    result = _call(headers, "search", {"query": query})
    assert not result.isError, result
    payload = _text_payload(result)
    assert result.structuredContent == payload
    return payload["results"]


def test_mcp_search_then_fetch_returns_stable_ids_and_full_text(
    admin_user: DATestUser,
) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)
    api_key = APIKeyManager.create(user_performing_action=admin_user)
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    text = "MCP fetch flow document about the Zürich travel policy"
    doc = DocumentManager.seed_doc_with_content(cc_pair, text, api_key)
    DocumentManager.wait_until_searchable([text], user_performing_action=admin_user)
    headers = _auth_headers(admin_user, "mcp-fetch-flow")

    first = _search_ids(headers, text)
    second = _search_ids(headers, text)
    hit = next(result for result in first if result["id"] == doc.id)
    assert hit["id"] in {result["id"] for result in second}
    assert len({result["id"] for result in first}) == len(first)
    # The seeded link is not an absolute URL, so the citation opens in Onyx.
    url = urlsplit(hit["url"])
    assert url.path == "/app/document"
    assert parse_qs(url.query)["id"] == [doc.id]

    fetched = _call(headers, "fetch", {"id": hit["id"]})
    assert not fetched.isError, fetched
    payload = _text_payload(fetched)
    assert fetched.structuredContent == payload
    assert payload["id"] == doc.id
    assert text in payload["text"]
    assert payload["url"] == hit["url"]
    assert payload["metadata"]["source_type"]


@pytest.mark.skipif(
    os.environ.get("RUN_EE_TESTS", "").lower() != "true",
    reason="User group permissions are Enterprise-only",
)
def test_mcp_fetch_hides_documents_the_caller_cannot_access(
    admin_user: DATestUser,
) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)
    suffix = uuid4().hex[:8]
    blocked_user = UserManager.create(name=f"mcp-fetch-blocked-{suffix}")
    allowed_user = UserManager.create(name=f"mcp-fetch-allowed-{suffix}")
    api_key = APIKeyManager.create(user_performing_action=admin_user)
    group = UserGroupManager.create(
        user_ids=[allowed_user.id], user_performing_action=admin_user
    )
    private_cc_pair = CCPairManager.create_from_scratch(
        access_type=AccessType.PRIVATE,
        data_access=[group.id],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user, user_groups_to_check=[group]
    )
    doc = DocumentManager.seed_doc_with_content(
        private_cc_pair, "MCP private fetch document", api_key
    )
    DocumentManager.wait_until_searchable(
        ["MCP private fetch document"], user_performing_action=allowed_user
    )

    allowed = _call(_auth_headers(allowed_user, "allowed"), "fetch", {"id": doc.id})
    assert not allowed.isError, allowed

    blocked_headers = _auth_headers(blocked_user, "blocked")
    blocked = _call(blocked_headers, "fetch", {"id": doc.id})
    missing = _call(blocked_headers, "fetch", {"id": "no-such-document"})
    assert blocked.isError and missing.isError
    blocked_error = _text_payload(blocked)["error"]
    assert blocked_error == _text_payload(missing)["error"].replace(
        "no-such-document", doc.id
    )
    assert "MCP private fetch document" not in blocked_error


def test_mcp_failures_set_is_error_and_empty_results_do_not(
    admin_user: DATestUser,
) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)
    api_key = APIKeyManager.create(user_performing_action=admin_user)
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    DocumentManager.seed_doc_with_content(cc_pair, "MCP error test document", api_key)
    headers = _auth_headers(admin_user, "mcp-errors")

    bad_date = _call(
        headers,
        "search_indexed_documents",
        {"query": "anything", "time_cutoff": "last tuesday"},
    )
    assert bad_date.isError
    assert "time_cutoff" in _text_payload(bad_date)["error"]

    empty = _call(
        headers,
        "search_indexed_documents",
        {
            "query": "qzxv unmatched",
            "retrieval_only": True,
            "time_cutoff": "2999-01-01",
        },
    )
    assert not empty.isError, empty
    assert _text_payload(empty)["results"] == []


def test_mcp_tools_are_annotated_read_only(admin_user: DATestUser) -> None:
    headers = _auth_headers(admin_user, "mcp-annotations")

    async def _action(session: ClientSession) -> Any:
        await session.initialize()
        return await session.list_tools()

    tools = {tool.name: tool for tool in _run_with_mcp_session(headers, _action).tools}
    assert READ_ONLY_TOOLS <= set(tools)
    for name in READ_ONLY_TOOLS:
        annotations = tools[name].annotations
        assert annotations is not None and annotations.readOnlyHint, name
        assert tools[name].title, name
    assert tools["search_web"].annotations.openWorldHint  # type: ignore[union-attr]
    assert not tools["fetch"].annotations.openWorldHint  # type: ignore[union-attr]
    for name in ("search", "fetch"):
        assert tools[name].outputSchema is not None, name


def _rpc(method: str, request_id: int, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def test_mcp_server_is_stateless_and_checks_origin(admin_user: DATestUser) -> None:
    headers = {
        **_auth_headers(admin_user, "mcp-stateless"),
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
    }
    url = f"{MCP_SERVER_URL.rstrip('/')}/"
    with httpx.Client(timeout=30) as client:
        initialized = client.post(
            url,
            headers=headers,
            json=_rpc(
                "initialize",
                1,
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "stateless-test", "version": "1"},
                },
            ),
        )
        assert initialized.status_code == 200, initialized.text
        assert "mcp-session-id" not in initialized.headers

        # No session id: any replica can serve the next request.
        listed = client.post(url, headers=headers, json=_rpc("tools/list", 2, {}))
        assert listed.status_code == 200, listed.text
        assert '"search"' in listed.text

        evil = client.post(
            url,
            headers={**headers, "Origin": "https://evil.example"},
            json=_rpc("tools/list", 3, {}),
        )
        assert evil.status_code == 403
