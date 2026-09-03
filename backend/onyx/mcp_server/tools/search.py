"""Search tools for MCP server - document and web search."""

import difflib
import time
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import httpx
from fastmcp.server.auth.auth import AccessToken
from pydantic import BaseModel, TypeAdapter, ValidationError

from onyx.configs.app_configs import MCP_SERVER_API_REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.mcp_server.api import mcp_server
from onyx.mcp_server.utils import (
    AgentEntry,
    get_accessible_agents,
    get_accessible_document_sets,
    get_http_client,
    get_indexed_sources,
    require_access_token,
)
from onyx.server.features.search.models import (
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from onyx.server.features.web_search.models import (
    OpenUrlsToolRequest,
    OpenUrlsToolResponse,
    WebSearchToolRequest,
    WebSearchToolResponse,
)
from onyx.server.metrics.mcp_common import MCPToolCallStatus
from onyx.server.metrics.mcp_server import (
    UNKNOWN_SOURCE_LABEL,
    MCPServerToolName,
    record_mcp_search_results,
    record_mcp_search_source,
    record_mcp_server_tool_outcome,
)
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
        timeout=httpx.Timeout(
            float(MCP_SERVER_API_REQUEST_TIMEOUT_SECONDS), connect=10.0
        ),
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

# A full inventory duplicates the matching resource and costs tokens on every
# failed call, so prefer near misses and only list everything when the
# inventory is small enough to be cheap.
_MAX_SUGGESTIONS = 5
_SUGGESTION_CUTOFF = 0.6
_MAX_NAMES_IN_ERROR = 10


def _match_agents(agent: str, agents: list[AgentEntry]) -> list[AgentEntry]:
    """Match an agent by name, preferring an exact hit over a case-fold one."""
    exact = [entry for entry in agents if entry.name == agent]
    if exact:
        return exact
    folded = agent.casefold()
    return [entry for entry in agents if entry.name.casefold() == folded]


def _unknown_value_error(
    kind: str, supplied: str, available: Iterable[str], discover: str
) -> str:
    """Explain an unusable filter value without dumping the whole inventory.

    Near misses cover the common cause — a human-supplied name that is stale or
    colloquial. When nothing is close the value has most likely been renamed or
    removed, so say that instead. Either way the call fails rather than dropping
    the filter, because a silently widened search reads as if it were scoped.
    """
    names = sorted(available)
    if not names:
        return f"{kind} '{supplied}' not found. None are accessible to this user."

    suggestions = difflib.get_close_matches(
        supplied, names, n=_MAX_SUGGESTIONS, cutoff=_SUGGESTION_CUTOFF
    )
    if suggestions:
        return f"{kind} '{supplied}' not found. Did you mean: {', '.join(suggestions)}?"

    if len(names) <= _MAX_NAMES_IN_ERROR:
        return f"{kind} '{supplied}' not found. Available: {', '.join(names)}."

    return (
        f"{kind} '{supplied}' not found — it may have been renamed or removed. "
        f"{discover}"
    )


def _record_requested_sources(source_types: list[str] | None) -> None:
    canonical_sources: set[str] = set()
    for source in source_types or []:
        try:
            canonical_sources.add(DocumentSource(source.lower()).value)
        except ValueError:
            canonical_sources.add(UNKNOWN_SOURCE_LABEL)
    for source in canonical_sources:
        record_mcp_search_source(source)


@mcp_server.tool()
async def search_indexed_documents(
    query: str,
    source_types: list[str] | None = None,
    document_set_names: list[str] | None = None,
    time_cutoff: str | None = None,
    skip_query_expansion: bool = False,
    agent: str | None = None,
) -> dict[str, Any]:
    """
    Search the user's knowledge base indexed in Onyx.
    Use this tool for information that is not public knowledge and specific to the user,
    their team, their work, or their organization/company.

    Runs the full Onyx search pipeline (LLM query expansion, hybrid retrieval,
    document selection, context expansion) — the same search quality as the
    Onyx chat interface.

    `source_types` restricts results to the named connector sources, and
    `document_set_names` to documents in the named Document Sets — useful for
    scoping a query to a curated subset of the knowledge base. Pass the values
    the user gave you; no lookup call is needed first. A value that does not
    resolve returns an error naming close matches or what is available, so you
    can retry with a valid one rather than searching unscoped.
    `time_cutoff` accepts an ISO 8601 timestamp; only documents updated on or
    after that moment are returned. Naive (timezone-less) timestamps are
    treated as UTC server-side.
    `skip_query_expansion` bypasses the LLM query-expansion step; useful when
    you already know the exact phrase to search for (faster, no LLM call for
    expansion).
    `agent` runs the search as a named Onyx agent, applying that agent's
    knowledge scope (its document sets, attached documents and start date) and
    its configured model. It resolves the same way as the filters above.
    `agent` and `document_set_names` are mutually exclusive: explicit document
    sets replace an agent's knowledge scope rather than narrowing it, so passing
    both is rejected.

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

    Scoping the same question to an agent instead:
    ```
    {
        "query": "What is the latest status of PROJ-1234?",
        "agent": "Engineering Support",
    }
    ```
    """
    _start = time.monotonic()
    tool = MCPServerToolName.SEARCH_INDEXED_DOCUMENTS
    logger.info(
        "Onyx MCP Server: document search: query='%s', sources=%s, document_sets=%s, agent=%s",
        query,
        source_types,
        document_set_names,
        agent,
    )

    _record_requested_sources(source_types)

    # Normalize empty list inputs to None so downstream filter construction is
    # consistent — BaseFilters treats [] as "match zero" which differs from
    # "no filter" (None).
    source_types = source_types or None
    document_set_names = document_set_names or None
    agent = (agent or "").strip() or None

    # Get authenticated user from FastMCP's access token
    access_token = require_access_token()
    outcome = MCPToolCallStatus.ERROR
    result_count: int | None = None

    try:
        # _build_index_filters lets explicit document sets *replace* the
        # agent's own sets rather than narrow them, so honouring both would
        # silently search outside the agent's knowledge scope.
        if agent is not None and document_set_names is not None:
            return _error_payload(
                "Pass either `agent` or `document_set_names`, not both. Explicit "
                "document sets replace an agent's knowledge scope instead of "
                "narrowing it, so the results would not be scoped to the agent."
            )

        # Resolve the agent before the indexed-sources guard below: a bad name
        # deserves its own actionable error, and an agent can carry attached
        # documents even when no connector has indexed anything.
        persona_id: int | None = None
        if agent is not None:
            try:
                accessible_agents = await get_accessible_agents(access_token)
            except Exception as err:
                logger.error(
                    "Onyx MCP Server: Error fetching agents: %s", err, exc_info=True
                )
                return _error_payload(f"Failed to look up agents: {str(err)}")

            matches = _match_agents(agent, accessible_agents)
            if not matches:
                return _error_payload(
                    _unknown_value_error(
                        "Agent",
                        agent,
                        (entry.name for entry in accessible_agents),
                        "Read the `agents` resource for the current list.",
                    )
                )
            if len(matches) > 1:
                return _error_payload(
                    f"Agent name '{agent}' is ambiguous: {len(matches)} accessible "
                    "agents share it. Ask the user which one they mean."
                )
            persona_id = matches[0].id

        # Needed for the empty-tenant guard, and to validate a source_types
        # filter against what this tenant actually has.
        indexed_sources: list[str] = []
        if agent is None or source_types is not None:
            try:
                indexed_sources = await get_indexed_sources(access_token)
            except Exception as err:
                logger.error(
                    "Onyx MCP Server: Error checking indexed sources: %s",
                    err,
                    exc_info=True,
                )
                return _error_payload(f"Failed to check indexed sources: {str(err)}")

        if agent is None and not indexed_sources:
            logger.info("Onyx MCP Server: No indexed sources available for tenant")
            outcome = MCPToolCallStatus.SUCCESS
            result_count = 0
            return _error_payload(
                "No document sources are indexed yet. Add connectors or upload data "
                "through Onyx before calling search_indexed_documents."
            )

        # An unusable filter value fails instead of being dropped: a silently
        # widened search is indistinguishable from a correctly scoped one.
        source_type_enums: list[DocumentSource] | None = None
        if source_types is not None:
            available_sources = set(indexed_sources)
            source_type_enums = []
            for source_str in source_types:
                canonical = source_str.lower()
                if canonical not in available_sources:
                    return _error_payload(
                        _unknown_value_error(
                            "Source type",
                            source_str,
                            available_sources,
                            "Read the `indexed_sources` resource for the current list.",
                        )
                    )
                source_type_enums.append(DocumentSource(canonical))

        if document_set_names is not None:
            try:
                accessible_sets = await get_accessible_document_sets(access_token)
            except Exception as err:
                logger.error(
                    "Onyx MCP Server: Error fetching document sets: %s",
                    err,
                    exc_info=True,
                )
                return _error_payload(f"Failed to look up document sets: {str(err)}")

            available_set_names = {entry.name for entry in accessible_sets}
            for set_name in document_set_names:
                if set_name not in available_set_names:
                    return _error_payload(
                        _unknown_value_error(
                            "Document set",
                            set_name,
                            available_set_names,
                            "Read the `document_sets` resource for the current list.",
                        )
                    )

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
            persona_id=persona_id,
        )
        endpoint = f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/search"
        response = await _post_model(endpoint, request, access_token)
        if not response.is_success:
            return _error_payload(_extract_error_detail(response))

        payload = SearchResponse.model_validate_json(response.content)
        results = [_to_mcp_dict(result) for result in payload.results]
        outcome = MCPToolCallStatus.SUCCESS
        result_count = len(results)
        logger.info(
            "Onyx MCP Server: Internal search returned %s results", len(results)
        )
        return {"results": results}
    except Exception as err:
        logger.error("Onyx MCP Server: Document search error: %s", err, exc_info=True)
        return _error_payload(f"Document search failed: {str(err)}")
    finally:
        record_mcp_server_tool_outcome(tool, _start, outcome)
        if result_count is not None:
            record_mcp_search_results(tool, result_count)


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
    _start = time.monotonic()
    tool = MCPServerToolName.SEARCH_WEB
    logger.info("Onyx MCP Server: Web search: query='%s', limit=%s", query, limit)

    access_token = require_access_token()
    outcome = MCPToolCallStatus.ERROR
    result_count: int | None = None

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
        outcome = MCPToolCallStatus.SUCCESS
        result_count = len(payload.results)
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
    finally:
        record_mcp_server_tool_outcome(tool, _start, outcome)
        if result_count is not None:
            record_mcp_search_results(tool, result_count)


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
    _start = time.monotonic()
    tool = MCPServerToolName.OPEN_URLS
    logger.info("Onyx MCP Server: Open URL: fetching %s URLs", len(urls))

    access_token = require_access_token()
    outcome = MCPToolCallStatus.ERROR

    try:
        response = await _post_model(
            f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/web-search/open-urls",
            OpenUrlsToolRequest(urls=urls),
            access_token,
        )
        if not response.is_success:
            return _error_payload(_extract_error_detail(response))
        payload = OpenUrlsToolResponse.model_validate_json(response.content)
        outcome = MCPToolCallStatus.SUCCESS
        return {
            "results": [result.model_dump(mode="json") for result in payload.results],
        }
    except Exception as err:
        logger.error("Onyx MCP Server: URL fetch error: %s", err, exc_info=True)
        return _error_payload(f"URL fetch failed: {str(err)}")
    finally:
        record_mcp_server_tool_outcome(tool, _start, outcome)
