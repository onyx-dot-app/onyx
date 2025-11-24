"""Search tools for MCP server - document and web search."""

from datetime import datetime
from typing import Any

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


@mcp_server.tool()
async def search_indexed_documents(
    query: str,
    source_types: list[str] | None = None,
    time_cutoff: datetime | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Search the user's knowledge base indexed in Onyx.
    Use this tool for information that is not public knowledge and specific to the user,
    their team, their work, or their organization/company.

    To find a list of available sources, use the `indexed_sources` resource.
    Returns chunks of text as search results with snippets, scores, and metadata.

    Example usage:
    ```
    {
        "query": "What is the latest status of PROJ-1234 and what is the next development item?",
        "source_types": ["jira", "google_drive", "github"],
        "limit": 10,
    }
    ```
    """
    logger.info(
        f"Onyx MCP Server: document search: query='{query}', sources={source_types}, limit={limit}"
    )

    # Initialize source_type_enums early to avoid UnboundLocalError
    source_type_enums: list[DocumentSource] | None = None

    # Get authenticated user from FastMCP's access token
    access_token = require_access_token()

    try:
        sources = await fetch_indexed_source_types(access_token)
    except Exception as e:
        # Error fetching sources (network error, API failure, etc.)
        logger.error(
            "Onyx MCP Server: Error checking indexed sources: %s",
            e,
            exc_info=True,
        )
        return {
            "documents": [],
            "total_results": 0,
            "query": query,
            "error": (f"Failed to check indexed sources: {str(e)}. "),
        }

    if not sources:
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
    if source_types is not None:
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
    fields_to_return = [
        "semantic_identifier",
        "content",
        "source_type",
        "link",
        "score",
    ]
    documents = [
        {key: doc.get(key) for key in fields_to_return}
        for doc in result.get("top_documents", [])
    ]

    logger.info(f"Onyx MCP Server: Internal search returned {len(documents)} results")
    return {
        "documents": documents,
        "total_results": len(documents),
        "query": query,
    }


@mcp_server.tool()
async def search_web(
    query: str,
    limit: int = 5,
) -> dict[str, Any]:
    """
    Search the public internet for general knowledge, current events, and publicly available information.
    Use this tool for information that is publicly available on the web,
    such as news, documentation, general facts, or when the user's private knowledge base doesn't contain relevant information.

    Returns web search results with titles, URLs, and snippets (NOT full content). Use `open_urls` to fetch full page content.

    Example usage:
    ```
    {
        "query": "React 19 migration guide to use react compiler",
        "limit": 5
    }
    ```
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
async def open_urls(
    urls: list[str],
) -> dict[str, Any]:
    """
    Retrieve the complete text content from specific web URLs.
    Use this tool when you need to access full content from known URLs,
    such as documentation pages or articles returned by the `search_web` tool.

    Useful for following up on web search results when snippets do not provide enough information.

    Returns the full text content of each URL along with metadata like title and content type.

    Example usage:
    ```
    {
        "urls": ["https://react.dev/versions", "https://react.dev/learn/react-compiler","https://react.dev/learn/react-compiler/introduction"]
    }
    ```
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
