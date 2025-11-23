"""Search tools for MCP server - document and web search."""

from datetime import datetime
from typing import Any

from fastmcp.server.auth import AccessToken

from ee.onyx.server.query_and_chat.models import DocumentSearchRequest
from onyx.configs.constants import DocumentSource
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.enums import SearchType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import RetrievalDetails
from onyx.mcp_server.api import mcp_server
from onyx.mcp_server.utils import fetch_indexed_source_types
from onyx.mcp_server.utils import get_api_server_url
from onyx.mcp_server.utils import get_http_client
from onyx.mcp_server.utils import require_access_token
from onyx.utils.logger import setup_logger

logger = setup_logger()


async def _tenant_has_indexed_sources(access_token: AccessToken) -> bool:
    """Check if the current tenant has any indexed document sources."""
    try:
        sources = await fetch_indexed_source_types(access_token)
        if sources is None:
            logger.warning("Onyx MCP Server: Failed to determine indexed sources.")
            return False
        return len(sources) > 0
    except Exception:
        logger.warning(
            "Onyx MCP Server: Failed to determine indexed sources.",
            exc_info=True,
        )
        return False


@mcp_server.tool()
async def onyx_search_documents(
    query: str,
    source_types: list[str] | None = None,
    time_cutoff: datetime | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Search Onyx's indexed knowledge base with optional filters.

    Returns ranked search results with snippets, scores, and metadata.

    Args:
        query: Search query string
        source_types: Filter by source types (e.g., ['confluence', 'github'])
        time_cutoff: Only return documents updated after this timestamp
        limit: Maximum results to return (1-50)

    Returns:
        Dict with:
        - documents: List of search results with content snippets
        - total_results: Number of results found
        - query: The query that was searched
    """
    logger.info(
        f"Onyx MCP Server: document search: query='{query}', sources={source_types}, limit={limit}"
    )

    # Get authenticated user from FastMCP's access token
    access_token = require_access_token()

    if not await _tenant_has_indexed_sources(access_token):
        logger.info("Onyx MCP Server: No indexed sources available for tenant")
        return {
            "documents": [],
            "total_results": 0,
            "query": query,
            "message": (
                "No document sources are indexed yet. Add connectors or upload data "
                "through Onyx before calling onyx_search_documents."
            ),
        }

    # Convert source_types strings to DocumentSource enums if provided
    # Invalid values will be handled by the API server
    source_type_enums = None
    if source_types:
        source_type_enums = []
        for src in source_types:
            try:
                source_type_enums.append(DocumentSource(src.lower()))
            except ValueError:
                logger.warning(
                    f"Onyx MCP Server: Invalid source type '{src}' - will be ignored by server"
                )

    search_request = DocumentSearchRequest(
        message=query,
        search_type=SearchType.SEMANTIC,
        retrieval_options=RetrievalDetails(
            filters=IndexFilters(
                source_type=source_type_enums,
                time_cutoff=time_cutoff,
                access_control_list=None,  # Server handles ACL using the access token
            ),
            enable_auto_detect_filters=False,
            offset=0,
            limit=limit,
        ),
        evaluation_type=LLMEvaluationType.SKIP,
    )

    # Call the API server
    response = await get_http_client().post(
        f"{get_api_server_url()}/query/document-search",
        json=search_request.model_dump(),
        headers={"Authorization": f"Bearer {access_token.token}"},
    )
    response.raise_for_status()
    result = response.json()

    # Return simplified format for MCP clients
    documents = [
        {
            "semantic_identifier": doc.get("semantic_identifier"),
            "content": doc.get("content"),
            "source_type": doc.get("source_type"),
            "link": doc.get("link"),
            "match_score": doc.get("score", 0.0),
        }
        for doc in result.get("top_documents", [])
    ]

    logger.info(f"Onyx MCP Server: Internal search returned {len(documents)} results")
    return {
        "documents": documents,
        "total_results": len(documents),
        "query": query,
    }


@mcp_server.tool()
async def onyx_web_search(
    query: str,
    limit: int = 5,
) -> dict[str, Any]:
    """
    Search the public web via Onyx's web search.

    Returns snippets only. Use `onyx_open_url` to fetch full content from URLs in these results.

    Args:
        query: Search query for the public web
        limit: Maximum results per query to return (1-20, default is 5)

    Returns:
        Dict with:
        - results: List of search results, each containing:
          - url: Web page URL
          - title: Page title
          - snippet: Brief excerpt (NOT full content)
        - query: The query that was searched
    """
    logger.info(f"Onyx MCP Server: Web search: query='{query}', limit={limit}")

    access_token = require_access_token()

    try:
        request_payload = {"queries": [query], "max_results": limit}
        response = await get_http_client().post(
            f"{get_api_server_url()}/web-search/search-lite",
            json=request_payload,
            headers={"Authorization": f"Bearer {access_token.token}"},
        )
        response.raise_for_status()
        response_payload = response.json()
        results = response_payload.get("results", [])
        return {
            "results": results,
            "query": query,
        }
    except Exception as e:
        logger.error(f"Onyx MCP Server: Web search error: {e}", exc_info=True)
        return {
            "error": f"Web search failed: {str(e)}",
            "results": [],
            "query": query,
        }


@mcp_server.tool()
async def onyx_open_url(
    urls: list[str],
) -> dict[str, Any]:
    """
    This tool retrieves the complete text content of web pages.

    Typical workflow:
    1. Use `onyx_web_search` to find relevant URLs (returns snippets only)
    2. Select the most promising URLs from search results
    3. Use THIS TOOL to fetch full page content from those URLs

    Args:
        urls: List of URLs to fetch full content from (e.g., URLs from web_search results)

    Returns:
        Dict with:
        - results: List of page content for each URL
    """
    logger.info(f"Onyx MCP Server: Open URL: fetching {len(urls)} URLs")

    access_token = require_access_token()

    try:
        response = await get_http_client().post(
            f"{get_api_server_url()}/web-search/open-urls",
            json={"urls": urls},
            headers={"Authorization": f"Bearer {access_token.token}"},
        )
        response.raise_for_status()
        response_payload = response.json()
        results = response_payload.get("results", [])
        return {
            "results": results,
        }
    except Exception as e:
        logger.error(f"Onyx MCP Server: URL fetch error: {e}", exc_info=True)
        return {
            "error": f"URL fetch failed: {str(e)}",
            "results": [],
        }
