"""Search tools for MCP server - document and web search."""

import os
from datetime import datetime
from typing import Any

import httpx
from fastmcp.server.dependencies import get_access_token

from ee.onyx.server.query_and_chat.models import DocumentSearchRequest
from onyx.configs.app_configs import APP_PORT
from onyx.configs.constants import DocumentSource
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.enums import SearchType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import RetrievalDetails
from onyx.mcp_server.api import mcp_server
from onyx.utils.logger import setup_logger

# Import mcp_server from api module (created there to avoid circular imports)

logger = setup_logger()

# Shared HTTP client for API requests (reused across requests)
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Get or create shared HTTP client for API requests."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


def _get_api_server_url() -> str:
    """Construct the API server URL for internal requests."""
    protocol = os.getenv("API_SERVER_PROTOCOL", "http")
    host = os.getenv("API_SERVER_HOST", "127.0.0.1")
    port = os.getenv("API_SERVER_PORT", str(APP_PORT))
    return f"{protocol}://{host}:{port}"


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
    Results are automatically filtered by user permissions and multi-tenant context.

    Args:
        query: Search query string
        source_types: Filter by source types (e.g., ['confluence', 'github'])
        time_cutoff: Only return documents updated after this timestamp
        limit: Maximum results to return (1-50)

    Returns:
        Dict with:
        - documents: List of search results with content snippets
        - total_results: Number of results found
    """
    logger.info(
        f"Onyx MCP server: document search: query='{query}', sources={source_types}, limit={limit}"
    )

    # Get authenticated user from FastMCP's access token
    access_token = get_access_token()
    if not access_token or "_user" not in access_token.claims:
        raise ValueError("Authentication required")

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
                    f"Invalid source type '{src}' - will be ignored by server"
                )

    # Build request payload - let API server handle validation and ACL
    search_request = DocumentSearchRequest(
        message=query,
        search_type=SearchType.SEMANTIC,
        retrieval_options=RetrievalDetails(
            filters=IndexFilters(
                source_type=source_type_enums,
                time_cutoff=time_cutoff,
                access_control_list=None,  # Server handles ACL
            ),
            enable_auto_detect_filters=False,
            offset=0,
            limit=limit,
        ),
        evaluation_type=LLMEvaluationType.SKIP,
    )

    # Call the API server
    response = await _get_http_client().post(
        f"{_get_api_server_url()}/query/document-search",
        json=search_request.model_dump(),
        headers={"Authorization": f"Bearer {access_token.token}"},
    )
    response.raise_for_status()
    result = response.json()

    # Return simplified format for MCP clients
    documents = [
        {
            "document_id": doc.get("document_id"),
            "semantic_identifier": doc.get("semantic_identifier"),
            "content": doc.get("content"),
            "source_type": doc.get("source_type"),
            "link": doc.get("link"),
            "match_score": doc.get("score", 0.0),
        }
        for doc in result.get("top_documents", [])
    ]

    logger.info(f"Search successful: {len(documents)} results")
    return {
        "documents": documents,
        "total_results": len(documents),
        "query": query,
    }


@mcp_server.tool()
async def onyx_web_search(
    query: str,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Search the public web using configured search provider (Exa or Serper+Firecrawl).

    IMPORTANT: This tool returns search results with SNIPPETS ONLY (URL, title, snippet).
    To read the full content of a web page, use the `onyx_open_url` tool with the URLs
    from these search results.

    Typical workflow:
    1. Use web_search to find relevant URLs
    2. Select the most promising URLs from results
    3. Use open_url to fetch full page content from selected URLs

    Requires web search to be configured with API keys:
    - Option 1: EXA_API_KEY environment variable
    - Option 2: SERPER_API_KEY + FIRECRAWL_API_KEY environment variables

    Returns error if web search is not configured.

    Args:
        query: Search query for the public web
        limit: Maximum results to return (1-20)

    Returns:
        Dict with:
        - results: List of search results, each containing:
          - url: Web page URL
          - title: Page title
          - snippet: Brief excerpt (NOT full content)
        - provider: Which search provider was used
        - total_results: Number of results found

        Or dict with error key if web search not configured

    Note: Use `onyx_open_url` to fetch full content from URLs in these results.
    """
    logger.info(f"Web search: query='{query}', limit={limit}")

    try:
        # Import from tool_implementations_v2 (same module as open_url)
        from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
            get_default_provider,
        )

        # Get search provider (same provider used by web_search and open_url)
        search_provider = get_default_provider()
        if search_provider is None:
            logger.warning("Web search provider not configured")
            return {
                "error": (
                    "Web search is not configured. "
                    "Please set EXA_API_KEY or (SERPER_API_KEY + FIRECRAWL_API_KEY) "
                    "environment variables."
                ),
                "results": [],
                "total_results": 0,
            }

        # Run web search using provider
        logger.debug(
            f"Running web search with provider: {type(search_provider).__name__}"
        )
        search_results = search_provider.search(query)

        # Format results (limit to requested amount)
        if search_results:
            results = [
                {
                    "url": result.link,
                    "title": result.title,
                    "snippet": result.snippet or "",
                }
                for result in search_results[:limit]
            ]
        else:
            results = []

        logger.info(f"Web search successful: {len(results)} results")

        return {
            "results": results,
            "provider": getattr(search_provider, "provider_type", "unknown"),
            "total_results": len(results),
            "query": query,
        }

    except ImportError as e:
        logger.error(f"Web search provider import failed: {e}")
        return {
            "error": f"Web search provider not available: {str(e)}",
            "results": [],
            "total_results": 0,
        }
    except Exception as e:
        logger.error(f"Web search error: {e}", exc_info=True)
        return {
            "error": f"Web search failed: {str(e)}",
            "results": [],
            "total_results": 0,
        }


@mcp_server.tool()
async def onyx_open_url(
    urls: list[str],
) -> dict[str, Any]:
    """
    Fetch and extract FULL CONTENT from web URLs.

    This tool retrieves the complete text content of web pages, not just snippets.

    Typical workflow:
    1. Use `onyx_web_search` to find relevant URLs (returns snippets only)
    2. Select the most promising URLs from search results
    3. Use THIS TOOL to fetch full page content from those URLs

    Uses the same search provider as web_search (Exa or Serper+Firecrawl).

    Requires web search to be configured with API keys:
    - Option 1: EXA_API_KEY environment variable
    - Option 2: SERPER_API_KEY + FIRECRAWL_API_KEY environment variables

    Returns error if web search provider is not configured.

    Args:
        urls: List of URLs to fetch full content from (e.g., URLs from web_search results)

    Returns:
        Dict with:
        - results: List of page content for each URL, each containing:
          - url: The fetched URL
          - title: Page title
          - content: FULL page content (truncated if extremely long)
          - success: Whether fetch was successful
        - provider: Which provider was used
        - total_results: Number of URLs successfully fetched

        Or dict with error key if not configured

    Note: This returns FULL page content, unlike `onyx_web_search` which only returns snippets.
    """
    logger.info(f"Open URL: fetching {len(urls)} URLs")

    try:
        # Import from tool_implementations_v2
        from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
            get_default_provider,
        )
        from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
            truncate_search_result_content,
        )

        # Get provider
        search_provider = get_default_provider()
        if search_provider is None:
            logger.warning("Web search provider not configured")
            return {
                "error": (
                    "Web search provider is not configured. "
                    "Please set EXA_API_KEY or (SERPER_API_KEY + FIRECRAWL_API_KEY) "
                    "environment variables."
                ),
                "results": [],
                "total_results": 0,
            }

        # Fetch content from URLs
        logger.debug(f"Fetching content from {len(urls)} URLs")
        docs = search_provider.contents(urls)

        # Format results
        results = []
        for doc in docs:
            results.append(
                {
                    "url": doc.link,
                    "title": getattr(doc, "title", ""),
                    "content": truncate_search_result_content(doc.full_content),
                    "success": True,
                }
            )

        logger.info(f"URL fetch successful: {len(results)} URLs processed")

        return {
            "results": results,
            "provider": getattr(search_provider, "provider_type", "unknown"),
            "total_results": len(results),
        }

    except ImportError as e:
        logger.error(f"URL fetch import failed: {e}")
        return {
            "error": f"Web provider not available: {str(e)}",
            "results": [],
            "total_results": 0,
        }
    except Exception as e:
        logger.error(f"URL fetch error: {e}", exc_info=True)
        return {
            "error": f"URL fetch failed: {str(e)}",
            "results": [],
            "total_results": 0,
        }
