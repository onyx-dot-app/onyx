"""Integration tests covering MCP document search flows."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from typing import Any

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult
from mcp.types import TextContent
from pydantic import AnyUrl

from onyx.db.enums import AccessType
from tests.integration.common_utils.constants import MCP_SERVER_URL
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.document_set import DocumentSetManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestUser


# Constants
MCP_SEARCH_TOOL = "search_indexed_documents"
INDEXED_SOURCES_RESOURCE_URI = "resource://indexed_sources"
DOCUMENT_SETS_RESOURCE_URI = "resource://document_sets"
DEFAULT_SEARCH_LIMIT = 5
STREAMABLE_HTTP_URL = f"{MCP_SERVER_URL.rstrip('/')}/?transportType=streamable-http"


def _run_with_mcp_session(
    headers: dict[str, str],
    action: Callable[[ClientSession], Awaitable[Any]],
) -> Any:
    """Run an async action with an MCP client session."""

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
    """Extract JSON payload from MCP tool result."""
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
    headers: dict[str, str],
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
    document_set_names: list[str] | None = None,
) -> CallToolResult:
    """Call the search_indexed_documents tool via MCP."""

    async def _action(session: ClientSession) -> CallToolResult:
        await session.initialize()
        arguments: dict[str, Any] = {
            "query": query,
            "limit": limit,
        }
        if document_set_names is not None:
            arguments["document_set_names"] = document_set_names
        return await session.call_tool(MCP_SEARCH_TOOL, arguments)

    return _run_with_mcp_session(headers, _action)


def _auth_headers(user: DATestUser, name: str) -> dict[str, str]:
    """Create authorization headers with a PAT token."""
    pat = PATManager.create(
        name=name,
        expiration_days=7,
        user_performing_action=user,
    )
    return {"Authorization": f"Bearer {pat.token}"}


def _seed_document_and_wait_for_indexing(
    cc_pair: DATestCCPair,
    content: str,
    api_key: DATestAPIKey,
    user_performing_action: DATestUser,
) -> None:
    """Seed a document and wait for indexing to complete."""
    before = datetime.now(timezone.utc)
    DocumentManager.seed_doc_with_content(
        cc_pair=cc_pair,
        content=content,
        api_key=api_key,
    )
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=user_performing_action,
    )


def test_mcp_document_search_flow(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Test the complete MCP search flow: initialization, resources, tools, and search."""
    # LLM provider is required for the document-search endpoint
    LLMProviderManager.create(user_performing_action=admin_user)

    api_key = APIKeyManager.create(user_performing_action=admin_user)
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)

    doc_text = "MCP happy path search document"
    _seed_document_and_wait_for_indexing(
        cc_pair=cc_pair,
        content=doc_text,
        api_key=api_key,
        user_performing_action=admin_user,
    )

    headers = _auth_headers(admin_user, name="mcp-search-flow")

    async def _full_flow(session: ClientSession) -> Any:
        await session.initialize()
        resources = await session.list_resources()
        tools = await session.list_tools()
        search_result = await session.call_tool(
            MCP_SEARCH_TOOL,
            {
                "query": doc_text,
                "limit": DEFAULT_SEARCH_LIMIT,
            },
        )
        return resources, tools, search_result

    resources_result, tools_result, search_result = _run_with_mcp_session(
        headers, _full_flow
    )

    # Verify resources are available
    resource_uris = {str(resource.uri) for resource in resources_result.resources}
    assert INDEXED_SOURCES_RESOURCE_URI in resource_uris

    # Verify tools are available
    tool_names = {tool.name for tool in tools_result.tools}
    assert MCP_SEARCH_TOOL in tool_names

    # Verify search results
    payload = _extract_tool_payload(search_result)
    assert payload["query"] == doc_text
    assert payload["total_results"] >= 1
    assert isinstance(payload["documents"], list)
    assert len(payload["documents"]) > 0
    assert any(doc_text in (doc.get("content") or "") for doc in payload["documents"])

    # Verify document structure
    for doc in payload["documents"]:
        assert isinstance(doc, dict)
        # Verify expected fields exist (may be None)
        assert "content" in doc
        assert "semantic_identifier" in doc
        assert "source_type" in doc


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group permissions are Enterprise-only",
)
def test_mcp_search_respects_acl_filters(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Test that search respects ACL filters - privileged users can access, others cannot."""
    # LLM provider is required for the document-search endpoint
    LLMProviderManager.create(user_performing_action=admin_user)

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
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user, user_groups_to_check=[user_group]
    )

    restricted_doc_content = "MCP restricted knowledge base document"
    _seed_document_and_wait_for_indexing(
        cc_pair=restricted_cc_pair,
        content=restricted_doc_content,
        api_key=api_key,
        user_performing_action=admin_user,
    )

    privileged_headers = _auth_headers(privileged_user, "mcp-acl-allowed")
    restricted_headers = _auth_headers(user_without_access, "mcp-acl-blocked")

    # Privileged user should find the document
    allowed_result = _call_search_tool(privileged_headers, restricted_doc_content)
    allowed_payload = _extract_tool_payload(allowed_result)
    assert allowed_payload["total_results"] >= 1
    assert any(
        restricted_doc_content in (doc.get("content") or "")
        for doc in allowed_payload["documents"]
    )

    # User without access should not find the document
    blocked_result = _call_search_tool(restricted_headers, restricted_doc_content)
    blocked_payload = _extract_tool_payload(blocked_result)
    assert blocked_payload["total_results"] == 0
    assert blocked_payload["documents"] == []


def test_mcp_search_filters_by_document_set(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Passing document_set_names should scope results to the named set."""
    LLMProviderManager.create(user_performing_action=admin_user)

    api_key = APIKeyManager.create(user_performing_action=admin_user)
    cc_pair_in_set = CCPairManager.create_from_scratch(
        user_performing_action=admin_user,
    )
    cc_pair_out_of_set = CCPairManager.create_from_scratch(
        user_performing_action=admin_user,
    )

    shared_phrase = "document-set-filter-shared-phrase"
    in_set_content = f"{shared_phrase} inside curated set"
    out_of_set_content = f"{shared_phrase} outside curated set"

    _seed_document_and_wait_for_indexing(
        cc_pair=cc_pair_in_set,
        content=in_set_content,
        api_key=api_key,
        user_performing_action=admin_user,
    )
    _seed_document_and_wait_for_indexing(
        cc_pair=cc_pair_out_of_set,
        content=out_of_set_content,
        api_key=api_key,
        user_performing_action=admin_user,
    )

    doc_set = DocumentSetManager.create(
        cc_pair_ids=[cc_pair_in_set.id],
        user_performing_action=admin_user,
    )
    DocumentSetManager.wait_for_sync(
        user_performing_action=admin_user,
        document_sets_to_check=[doc_set],
    )

    headers = _auth_headers(admin_user, name="mcp-doc-set-filter")

    # The document_sets resource should surface the newly created set so MCP
    # clients can discover which values to pass to document_set_names.
    async def _list_resources(session: ClientSession) -> Any:
        await session.initialize()
        resources = await session.list_resources()
        contents = await session.read_resource(AnyUrl(DOCUMENT_SETS_RESOURCE_URI))
        return resources, contents

    resources_result, doc_sets_contents = _run_with_mcp_session(
        headers, _list_resources
    )
    resource_uris = {str(resource.uri) for resource in resources_result.resources}
    assert DOCUMENT_SETS_RESOURCE_URI in resource_uris
    doc_sets_payload = json.loads(doc_sets_contents.contents[0].text)
    exposed_names = {entry["name"] for entry in doc_sets_payload}
    assert doc_set.name in exposed_names

    # Without the filter both documents are visible.
    unfiltered_payload = _extract_tool_payload(
        _call_search_tool(headers, shared_phrase, limit=10)
    )
    unfiltered_contents = [
        doc.get("content") or "" for doc in unfiltered_payload["documents"]
    ]
    assert any(in_set_content in content for content in unfiltered_contents)
    assert any(out_of_set_content in content for content in unfiltered_contents)

    # With the document set filter only the in-set document is returned.
    filtered_payload = _extract_tool_payload(
        _call_search_tool(
            headers,
            shared_phrase,
            limit=10,
            document_set_names=[doc_set.name],
        )
    )
    filtered_contents = [
        doc.get("content") or "" for doc in filtered_payload["documents"]
    ]
    assert filtered_payload["total_results"] >= 1
    assert any(in_set_content in content for content in filtered_contents)
    assert all(out_of_set_content not in content for content in filtered_contents)

    # An empty document_set_names should behave like "no filter" (normalized
    # to None), not "match zero sets".
    empty_list_payload = _extract_tool_payload(
        _call_search_tool(
            headers,
            shared_phrase,
            limit=10,
            document_set_names=[],
        )
    )
    empty_list_contents = [
        doc.get("content") or "" for doc in empty_list_payload["documents"]
    ]
    assert any(in_set_content in content for content in empty_list_contents)
    assert any(out_of_set_content in content for content in empty_list_contents)
