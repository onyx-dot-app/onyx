"""Integration tests covering MCP document search flows."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult
from mcp.types import TextContent

from onyx.db.enums import AccessType
from tests.integration.common_utils.constants import MCP_SERVER_URL
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


MCP_SEARCH_TOOL = "search_indexed_documents"
STREAMABLE_HTTP_URL = MCP_SERVER_URL.rstrip("/") + "/?transportType=streamable-http"


def _run_with_mcp_session(
    headers: dict[str, str],
    action: Callable[[ClientSession], Awaitable[Any]],
) -> Any:
    async def _runner() -> Any:
        async with streamablehttp_client(STREAMABLE_HTTP_URL, headers=headers) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                return await action(session)

    return asyncio.run(_runner())


def _extract_tool_payload(result: CallToolResult) -> dict[str, Any]:
    if result.isError:
        raise AssertionError(f"MCP tool returned error: {result}")

    text_blocks = [
        block.text
        for block in result.content
        if isinstance(block, TextContent) and block.text
    ]
    if not text_blocks:
        raise AssertionError("Expected textual content from MCP tool result")

    return json.loads(text_blocks[-1])


def _call_search_tool(
    headers: dict[str, str], query: str, limit: int = 5
) -> CallToolResult:
    async def _action(session: ClientSession) -> CallToolResult:
        await session.initialize()
        return await session.call_tool(
            MCP_SEARCH_TOOL,
            {
                "query": query,
                "limit": limit,
            },
        )

    return _run_with_mcp_session(headers, _action)


def _auth_headers(user: DATestUser, name: str) -> dict[str, str]:
    token_data = PATManager.create(
        name=name,
        expiration_days=7,
        user_performing_action=user,
    )
    return {"Authorization": f"Bearer {token_data['token']}"}


def test_mcp_document_search_flow(reset: None, admin_user: DATestUser) -> None:
    api_key = APIKeyManager.create(user_performing_action=admin_user)
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)

    doc_text = "MCP happy path search document"
    _ = DocumentManager.seed_doc_with_content(
        cc_pair=cc_pair,
        content=doc_text,
        api_key=api_key,
    )

    headers = _auth_headers(admin_user, name="mcp-search-flow")

    async def _full_flow(
        session: ClientSession,
    ) -> tuple[Any, Any, Any, CallToolResult]:
        init_result = await session.initialize()
        resources = await session.list_resources()
        tools = await session.list_tools()
        search_result = await session.call_tool(
            MCP_SEARCH_TOOL,
            {
                "query": doc_text,
                "limit": 5,
            },
        )
        return init_result, resources, tools, search_result

    _, resources_result, tools_result, search_result = _run_with_mcp_session(
        headers, _full_flow
    )

    resource_uris = {str(resource.uri) for resource in resources_result.resources}
    assert "resource://indexed_sources" in resource_uris

    tool_names = {tool.name for tool in tools_result.tools}
    assert MCP_SEARCH_TOOL in tool_names

    payload = _extract_tool_payload(search_result)
    assert payload["query"] == doc_text
    assert payload["total_results"] >= 1
    assert any(doc_text in (doc.get("content") or "") for doc in payload["documents"])


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group permissions are Enterprise-only",
)
def test_mcp_search_respects_acl_filters(reset: None, admin_user: DATestUser) -> None:
    user_without_access = UserManager.create(name="mcp-acl-user-a")
    privileged_user = UserManager.create(name="mcp-acl-user-b")

    api_key = APIKeyManager.create(user_performing_action=admin_user)
    restricted_cc_pair = CCPairManager.create_from_scratch(
        access_type=AccessType.PRIVATE,
        user_performing_action=admin_user,
    )

    user_group = UserGroupManager.create(
        user_ids=[privileged_user.id],
        cc_pair_ids=[restricted_cc_pair.id],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync([user_group], user_performing_action=admin_user)

    restricted_doc = DocumentManager.seed_doc_with_content(
        cc_pair=restricted_cc_pair,
        content="MCP restricted knowledge base document",
        api_key=api_key,
    )

    privileged_headers = _auth_headers(privileged_user, "mcp-acl-allowed")
    restricted_headers = _auth_headers(user_without_access, "mcp-acl-blocked")

    allowed_result = _call_search_tool(privileged_headers, restricted_doc.content)
    allowed_payload = _extract_tool_payload(allowed_result)
    assert allowed_payload["total_results"] >= 1
    assert any(
        restricted_doc.content in (doc.get("content") or "")
        for doc in allowed_payload["documents"]
    )

    blocked_result = _call_search_tool(restricted_headers, restricted_doc.content)
    blocked_payload = _extract_tool_payload(blocked_result)
    assert blocked_payload["total_results"] == 0
