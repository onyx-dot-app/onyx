"""Search tools for MCP server - document and web search."""

from datetime import datetime
from typing import Any

import httpx
from fastmcp.server.auth.auth import AccessToken
from pydantic import BaseModel
from pydantic import TypeAdapter
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.mcp_server.api import mcp_server
from onyx.mcp_server.utils import get_http_client
from onyx.mcp_server.utils import get_indexed_sources
from onyx.mcp_server.utils import require_access_token
from onyx.server.features.search.models import SearchRequest
from onyx.server.features.search.models import SearchResponse
from onyx.server.features.search.models import SearchResult
from onyx.server.features.web_search.models import OpenUrlsToolRequest
from onyx.server.features.web_search.models import OpenUrlsToolResponse
from onyx.server.features.web_search.models import WebSearchToolRequest
from onyx.server.features.web_search.models import WebSearchToolResponse
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import build_api_server_url_for_http_requests

logger = setup_logger()


async def _post_model(
    url: str,
    body: BaseModel,
    access_token: AccessToken,
) -> httpx.Response:
    """POST a Pydantic model as JSON to the Onyx backend."""
    return await get_http_client().post(
        url,
        content=body.model_dump_json(exclude_unset=True),
        headers={
            "Authorization": f"Bearer {access_token.token}",
            "Content-Type": "application/json",
        },
    )


def _to_mcp_dict(result: SearchResult) -> dict[str, Any]:
    """Convert a search API result into the dict shape MCP clients receive.

    Renames ``link`` → ``url`` to match the conventional shape MCP tools
    typically emit (most search-style MCP tools — Brave, Exa, etc. — use
    ``url`` rather than ``link``).
    """
    return {
        "title": result.title,
        "url": result.link,
        "source_type": result.source_type,
        "content": result.content,
        "updated_at": result.updated_at,
    }


def _extract_error_detail(response: httpx.Response) -> str:
    """Extract a human-readable error message from a failed backend response.

    The backend returns OnyxError responses as
    ``{"error_code": "...", "detail": "..."}``.
    """
    try:
        body = response.json()
        if detail := body.get("detail"):
            return str(detail)
    except Exception as exc:
        logger.debug("Onyx MCP Server: error body was not JSON (%s)", exc)
    return f"Request failed with status {response.status_code}"


def _error_payload(error: str) -> dict[str, Any]:
    """Build the standard MCP error response envelope used by every tool."""
    return {"error": error, "results": []}


_TIME_CUTOFF_ADAPTER: TypeAdapter[datetime | None] = TypeAdapter(datetime | None)


@mcp_server.tool()
async def search_indexed_documents(
    query: str,
    source_types: list[str] | None = None,
    document_set_names: list[str] | None = None,
    time_cutoff: str | None = None,
    skip_query_expansion: bool = False,
) -> dict[str, Any]:
    """
    Search the user's knowledge base indexed in Onyx.
    Use this tool for information that is not public knowledge and specific to the user,
    their team, their work, or their organization/company.

    Runs the full Onyx search pipeline (LLM query expansion, hybrid retrieval,
    document selection, context expansion) — the same search quality as the
    Onyx chat interface.

    To find a list of available sources, use the `indexed_sources` resource.
    `document_set_names` restricts results to documents belonging to the named
    Document Sets — useful for scoping queries to a curated subset of the
    knowledge base (e.g. to isolate knowledge between agents). Use the
    `document_sets` resource to discover accessible set names.
    `time_cutoff` accepts an ISO 8601 timestamp; only documents updated on or
    after that moment are returned. Naive (timezone-less) timestamps are
    treated as UTC server-side.
    `skip_query_expansion` bypasses the LLM query-expansion step; useful when
    you already know the exact phrase to search for (faster, no LLM call for
    expansion).

    Returns ``{"results": [{title, url, source_type, content, updated_at},
    ...]}``. Results are ordered by LLM-judged relevance. ``content`` is the
    full chunk of the document the LLM selected; in the rare case the LLM
    selection step yields no full chunk for a doc, it falls back to the
    short search blurb.

    Example usage:
    ```
    {
        "query": "What is the latest status of PROJ-1234 and what is the next development item?",
        "source_types": ["jira", "google_drive", "github"],
        "document_set_names": ["Engineering Wiki"],
        "time_cutoff": "2025-11-24T00:00:00Z",
    }
    ```
    """
    logger.info(
        "Onyx MCP Server: document search: query='%s', sources=%s, document_sets=%s",
        query,
        source_types,
        document_set_names,
    )

    # Normalize empty list inputs to None so the API treats them as "no filter"
    # rather than "match zero".
    source_types = source_types or None
    document_set_names = document_set_names or None

    # Get authenticated user from FastMCP's access token
    access_token = require_access_token()

    try:
        sources = await get_indexed_sources(access_token)
    except Exception as err:
        logger.error(
            "Onyx MCP Server: Error checking indexed sources: %s",
            err,
            exc_info=True,
        )
        return _error_payload(f"Failed to check indexed sources: {str(err)}")

    if not sources:
        logger.info("Onyx MCP Server: No indexed sources available for tenant")
        return _error_payload(
            "No document sources are indexed yet. Add connectors or upload data "
            "through Onyx before calling search_indexed_documents."
        )

    # Convert source_types strings to DocumentSource enums; skip unknown values.
    source_type_enums: list[DocumentSource] | None = None
    if source_types is not None:
        source_type_enums = []
        for source_str in source_types:
            try:
                source_type_enums.append(DocumentSource(source_str.lower()))
            except ValueError:
                logger.warning(
                    "Onyx MCP Server: Invalid source type '%s' - skipping",
                    source_str,
                )

    # Parse time_cutoff via Pydantic (accepts ISO 8601 with offset, "Z",
    # naive, and date-only). Bad LLM-generated cutoffs fall back to no filter
    # so they can't break the whole call.
    try:
        parsed_cutoff = _TIME_CUTOFF_ADAPTER.validate_python(time_cutoff)
    except ValidationError as err:
        logger.warning(
            "Onyx MCP Server: invalid time_cutoff '%s' (%s); continuing without time filter",
            time_cutoff,
            err,
        )
        parsed_cutoff = None

    request = SearchRequest(
        query=query,
        sources=source_type_enums,
        document_sets=document_set_names,
        time_cutoff=parsed_cutoff,
        skip_query_expansion=skip_query_expansion,
    )

    endpoint = f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/search"
    try:
        response = await _post_model(endpoint, request, access_token)
        if not response.is_success:
            return _error_payload(_extract_error_detail(response))

        payload = SearchResponse.model_validate_json(response.content)
        results = [_to_mcp_dict(result) for result in payload.results]

        logger.info(
            "Onyx MCP Server: Internal search returned %s results", len(results)
        )
        return {"results": results}
    except Exception as err:
        logger.error("Onyx MCP Server: Document search error: %s", err, exc_info=True)
        return _error_payload(f"Document search failed: {str(err)}")


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
    logger.info("Onyx MCP Server: Web search: query='%s', limit=%s", query, limit)

    access_token = require_access_token()

    try:
        response = await _post_model(
            f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/web-search/search-lite",
            WebSearchToolRequest(queries=[query], max_results=limit),
            access_token,
        )
        if not response.is_success:
            return {
                "error": _extract_error_detail(response),
                "results": [],
                "query": query,
            }
        payload = WebSearchToolResponse.model_validate_json(response.content)
        return {
            "results": [result.model_dump(mode="json") for result in payload.results],
            "query": query,
        }
    except Exception as e:
        logger.error("Onyx MCP Server: Web search error: %s", e, exc_info=True)
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
    logger.info("Onyx MCP Server: Open URL: fetching %s URLs", len(urls))

    access_token = require_access_token()

    try:
        response = await _post_model(
            f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/web-search/open-urls",
            OpenUrlsToolRequest(urls=urls),
            access_token,
        )
        if not response.is_success:
            return _error_payload(_extract_error_detail(response))
        payload = OpenUrlsToolResponse.model_validate_json(response.content)
        return {
            "results": [result.model_dump(mode="json") for result in payload.results],
        }
    except Exception as err:
        logger.error("Onyx MCP Server: URL fetch error: %s", err, exc_info=True)
        return _error_payload(f"URL fetch failed: {str(err)}")
