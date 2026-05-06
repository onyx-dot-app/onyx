"""Search tools for MCP server - document and web search."""

from datetime import datetime
from typing import Any

import httpx
from fastmcp.server.auth.auth import AccessToken
from pydantic import BaseModel

from onyx.chat.models import ChatFullResponse
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import SearchDoc
from onyx.mcp_server.api import mcp_server
from onyx.mcp_server.utils import get_http_client
from onyx.mcp_server.utils import get_indexed_sources
from onyx.mcp_server.utils import require_access_token
from onyx.server.features.web_search.models import OpenUrlsToolRequest
from onyx.server.features.web_search.models import OpenUrlsToolResponse
from onyx.server.features.web_search.models import WebSearchToolRequest
from onyx.server.features.web_search.models import WebSearchToolResponse
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import build_api_server_url_for_http_requests
from onyx.utils.variable_functionality import global_version

logger = setup_logger()


# CE search falls through to the chat endpoint, which invokes an LLM — the
# default 60s client timeout is not enough for a real RAG-backed response.
_CE_SEARCH_TIMEOUT_SECONDS = 300.0


async def _post_model(
    url: str,
    body: BaseModel,
    access_token: AccessToken,
    timeout: float | None = None,
) -> httpx.Response:
    """POST a Pydantic model as JSON to the Onyx backend."""
    return await get_http_client().post(
        url,
        content=body.model_dump_json(exclude_unset=True),
        headers={
            "Authorization": f"Bearer {access_token.token}",
            "Content-Type": "application/json",
        },
        timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
    )


def _project_doc(doc: SearchDoc, content: str | None) -> dict[str, Any]:
    """Project a backend search doc into the MCP wire shape.

    Accepts SearchDocWithContent (EE) too since it extends SearchDoc.
    """
    return {
        "semantic_identifier": doc.semantic_identifier,
        "content": content,
        "source_type": doc.source_type.value,
        "link": doc.link,
        "score": doc.score,
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
    except Exception:
        pass
    return f"Request failed with status {response.status_code}"


@mcp_server.tool()
async def search_indexed_documents(
    query: str,
    source_types: list[str] | None = None,
    document_set_names: list[str] | None = None,
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
    `document_set_names` restricts results to documents belonging to the named
    Document Sets — useful for scoping queries to a curated subset of the
    knowledge base (e.g. to isolate knowledge between agents). Use the
    `document_sets` resource to discover accessible set names.
    Returns chunks of text as search results with snippets, scores, and metadata.

    Example usage:
    ```
    {
        "query": "What is the latest status of PROJ-1234 and what is the next development item?",
        "source_types": ["jira", "google_drive", "github"],
        "document_set_names": ["Engineering Wiki"],
        "time_cutoff": "2025-11-24T00:00:00Z",
        "limit": 10,
    }
    ```
    """
    logger.info(
        "Onyx MCP Server: document search: query='%s', sources=%s, document_sets=%s, limit=%s",
        query,
        source_types,
        document_set_names,
        limit,
    )

    # Normalize empty list inputs to None so downstream filter construction is
    # consistent — BaseFilters treats [] as "match zero" which differs from
    # "no filter" (None).
    source_types = source_types or None
    document_set_names = document_set_names or None

    # Parse time_cutoff string to datetime if provided
    time_cutoff_dt: datetime | None = None
    if time_cutoff:
        try:
            time_cutoff_dt = datetime.fromisoformat(time_cutoff.replace("Z", "+00:00"))
        except ValueError as e:
            logger.warning(
                "Onyx MCP Server: Invalid time_cutoff format '%s': %s. Continuing without time filter.",
                time_cutoff,
                e,
            )
            # Continue with no time_cutoff instead of returning an error
            time_cutoff_dt = None

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
    source_type_enums: list[DocumentSource] | None = None
    if source_types is not None:
        source_type_enums = []
        for src in source_types:
            try:
                source_type_enums.append(DocumentSource(src.lower()))
            except ValueError:
                logger.warning(
                    "Onyx MCP Server: Invalid source type '%s' - will be ignored by server",
                    src,
                )

    filters: BaseFilters | None = None
    if source_type_enums or document_set_names or time_cutoff_dt:
        filters = BaseFilters(
            source_type=source_type_enums,
            document_set=document_set_names,
            time_cutoff=time_cutoff_dt,
        )

    base_url = build_api_server_url_for_http_requests(respect_env_override_if_set=True)
    is_ee = global_version.is_ee_version()

    request: BaseModel
    if is_ee:
        # EE: use the dedicated search endpoint (no LLM invocation).
        # Lazy import so CE deployments that strip ee/ never load this module.
        from ee.onyx.server.query_and_chat.models import SendSearchQueryRequest

        request = SendSearchQueryRequest(
            search_query=query,
            filters=filters,
            num_docs_fed_to_llm_selection=limit,
            run_query_expansion=False,
            include_content=True,
            stream=False,
        )
        endpoint = f"{base_url}/search/send-search-message"
    else:
        # CE: fall back to the chat endpoint (invokes LLM, consumes tokens)
        request = SendMessageRequest(
            message=query,
            stream=False,
            chat_session_info=ChatSessionCreationRequest(),
            internal_search_filters=filters,
        )
        endpoint = f"{base_url}/chat/send-chat-message"

    try:
        response = await _post_model(
            endpoint,
            request,
            access_token,
            timeout=None if is_ee else _CE_SEARCH_TIMEOUT_SECONDS,
        )
        if not response.is_success:
            return {
                "documents": [],
                "total_results": 0,
                "query": query,
                "error": _extract_error_detail(response),
            }

        if is_ee:
            from ee.onyx.server.query_and_chat.models import SearchFullResponse

            ee_payload = SearchFullResponse.model_validate_json(response.content)
            if ee_payload.error:
                return {
                    "documents": [],
                    "total_results": 0,
                    "query": query,
                    "error": ee_payload.error,
                }
            documents = [
                _project_doc(doc, doc.content) for doc in ee_payload.search_docs
            ]
        else:
            ce_payload = ChatFullResponse.model_validate_json(response.content)
            if ce_payload.error_msg:
                return {
                    "documents": [],
                    "total_results": 0,
                    "query": query,
                    "error": ce_payload.error_msg,
                }
            documents = [
                _project_doc(doc, doc.blurb) for doc in ce_payload.top_documents
            ]

        # NOTE: search depth is controlled by the backend persona defaults, not `limit`.
        # `limit` only caps the returned list; fewer results may be returned if the
        # backend retrieves fewer documents than requested.
        documents = documents[:limit]

        logger.info(
            "Onyx MCP Server: Internal search returned %s results", len(documents)
        )
        return {
            "documents": documents,
            "total_results": len(documents),
            "query": query,
        }
    except Exception as e:
        logger.error("Onyx MCP Server: Document search error: %s", e, exc_info=True)
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
            return {
                "error": _extract_error_detail(response),
                "results": [],
            }
        payload = OpenUrlsToolResponse.model_validate_json(response.content)
        return {
            "results": [result.model_dump(mode="json") for result in payload.results],
        }
    except Exception as e:
        logger.error("Onyx MCP Server: URL fetch error: %s", e, exc_info=True)
        return {
            "error": f"URL fetch failed: {str(e)}",
            "results": [],
        }
