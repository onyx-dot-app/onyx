"""Search tools for MCP server - document and web search."""

from datetime import datetime
from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.mcp_server.api import mcp_server
from onyx.mcp_server.utils import get_http_client
from onyx.mcp_server.utils import get_indexed_sources
from onyx.mcp_server.utils import require_access_token
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import build_api_server_url_for_http_requests
from onyx.utils.variable_functionality import global_version

logger = setup_logger()


@mcp_server.tool()
async def search_indexed_documents(
    query: str,
    source_types: list[str] | None = None,
    time_cutoff: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Search the user's knowledge base indexed in Onyx.
    Use this tool for information that is not public knowledge and specific to the user,
    their team, their work, or their organization/company.

    Note: In CE mode, this tool uses the chat endpoint internally which invokes an LLM
    on every call, consuming tokens and adding latency.
    Additionally, CE callers receive a truncated snippet (blurb) instead of a full document chunk,
    but this should still be sufficient for most use cases. CE mode functionality should be swapped
    when a dedicated CE search endpoint is implemented.

    In EE mode, the dedicated search endpoint is used instead.

    To find a list of available sources, use the `indexed_sources` resource.
    Returns chunks of text as search results with snippets, scores, and metadata.

    Example usage:
    ```
    {
        "query": "What is the latest status of PROJ-1234 and what is the next development item?",
        "source_types": ["jira", "google_drive", "github"],
        "time_cutoff": "2025-11-24T00:00:00Z",
        "limit": 10,
    }
    ```
    """
    logger.info(
        f"Onyx MCP Server: document search: query='{query}', sources={source_types}, limit={limit}"
    )

    # Parse time_cutoff string to datetime if provided
    time_cutoff_dt: datetime | None = None
    if time_cutoff:
        try:
            time_cutoff_dt = datetime.fromisoformat(time_cutoff.replace("Z", "+00:00"))
        except ValueError as e:
            logger.warning(
                f"Onyx MCP Server: Invalid time_cutoff format '{time_cutoff}': {e}. Continuing without time filter."
            )
            # Continue with no time_cutoff instead of returning an error
            time_cutoff_dt = None

    # Initialize source_type_enums early to avoid UnboundLocalError
    source_type_enums: list[DocumentSource] | None = None

    # Get authenticated user from FastMCP's access token
    access_token = require_access_token()

    try:
        sources = await get_indexed_sources(access_token)
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

    # Build filters dict only with non-None values
    filters: dict[str, Any] | None = None
    if source_type_enums or time_cutoff_dt:
        filters = {}
        if source_type_enums:
            filters["source_type"] = [src.value for src in source_type_enums]
        if time_cutoff_dt:
            filters["time_cutoff"] = time_cutoff_dt.isoformat()

    is_ee = global_version.is_ee_version()
    base_url = build_api_server_url_for_http_requests(respect_env_override_if_set=True)
    auth_headers = {"Authorization": f"Bearer {access_token.token}"}

    search_request: dict[str, Any]
    if is_ee:
        # EE: use the dedicated search endpoint (no LLM invocation)
        search_request = {
            "search_query": query,
            "filters": filters,
            "num_docs_fed_to_llm_selection": limit,
            "run_query_expansion": False,
            "include_content": True,
            "stream": False,
        }
        endpoint = f"{base_url}/search/send-search-message"
        error_key = "error"
        docs_key = "search_docs"
        content_field = "content"
    else:
        # CE: fall back to the chat endpoint (invokes LLM, consumes tokens)
        search_request = {
            "message": query,
            "stream": False,
            "chat_session_info": {},
        }
        if filters:
            search_request["internal_search_filters"] = filters
        endpoint = f"{base_url}/chat/send-chat-message"
        error_key = "error_msg"
        docs_key = "top_documents"
        content_field = "blurb"

    try:
        response = await get_http_client().post(
            endpoint,
            json=search_request,
            headers=auth_headers,
        )
        response.raise_for_status()
        result = response.json()

        # Check for error in response
        if result.get(error_key):
            return {
                "documents": [],
                "total_results": 0,
                "query": query,
                "error": result.get(error_key),
            }

        documents = [
            {
                "semantic_identifier": doc.get("semantic_identifier"),
                "content": doc.get(content_field),
                "source_type": doc.get("source_type"),
                "link": doc.get("link"),
                "score": doc.get("score"),
            }
            for doc in result.get(docs_key, [])
        ]

        # NOTE: search depth is controlled by the backend persona defaults, not `limit`.
        # `limit` only caps the returned list; fewer results may be returned if the
        # backend retrieves fewer documents than requested.
        documents = documents[:limit]

        logger.info(
            f"Onyx MCP Server: Internal search returned {len(documents)} results"
        )
        return {
            "documents": documents,
            "total_results": len(documents),
            "query": query,
        }
    except Exception as e:
        logger.error(f"Onyx MCP Server: Document search error: {e}", exc_info=True)
        return {
            "error": f"Document search failed: {str(e)}",
            "documents": [],
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
            f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/web-search/search-lite",
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
            f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/web-search/open-urls",
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
