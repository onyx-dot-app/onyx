import json
import time
from typing import Any

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.context.search.models import SearchDocsResponse
from onyx.context.search.utils import convert_inference_sections_to_search_docs
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.web_search import fetch_active_web_search_provider
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDebugDelta
from onyx.server.query_and_chat.streaming_models import SearchToolDebugResult
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.models import WebSearchToolOverrideKwargs
from onyx.tools.tool_implementations.utils import (
    convert_inference_sections_to_llm_string,
)
from onyx.tools.tool_implementations.web_search.models import DEFAULT_MAX_RESULTS
from onyx.tools.tool_implementations.web_search.models import WebSearchMode
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
)
from onyx.tools.tool_implementations.web_search.providers import (
    provider_requires_api_key,
)
from onyx.tools.tool_implementations.web_search.utils import (
    filter_web_search_results_with_no_title_or_snippet,
)
from onyx.tools.tool_implementations.web_search.utils import (
    inference_section_from_internet_search_result,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from shared_configs.enums import WebSearchProviderType

logger = setup_logger()

QUERIES_FIELD = "queries"
MODE_FIELD = "mode"


def _get_safe_channel(config: Any) -> str | None:
    if isinstance(config, dict):
        channel = config.get("channel")
        if isinstance(channel, str) and channel.strip():
            return channel.strip()
    return None


def _sanitize_query(query: str) -> str:
    """Remove control characters and normalize whitespace in a query.

    LLMs sometimes produce queries with null characters or other control
    characters that need to be stripped before sending to search providers.
    """
    # Remove control characters (ASCII 0-31 and 127 DEL)
    sanitized = "".join(c for c in query if ord(c) >= 32 and ord(c) != 127)
    # Collapse multiple whitespace characters into single space and strip
    return " ".join(sanitized.split())


def _normalize_queries_input(raw: Any) -> list[str]:
    """Coerce LLM output to a list of sanitized query strings.

    Accepts a bare string or a list (possibly with non-string elements).
    Sanitizes each query (strip control chars, normalize whitespace) and
    drops empty or whitespace-only entries.
    """
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        raw = [raw]
    elif not isinstance(raw, list):
        return []
    result: list[str] = []
    for q in raw:
        if q is None:
            continue
        sanitized = _sanitize_query(str(q))
        if sanitized:
            result.append(sanitized)
    return result


def _normalize_mode_input(raw: Any, default_mode: WebSearchMode) -> WebSearchMode:
    if raw is None:
        return default_mode
    if isinstance(raw, WebSearchMode):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        try:
            return WebSearchMode(normalized)
        except ValueError as exc:
            raise ToolCallException(
                message=f"Invalid web search mode: {raw}",
                llm_facing_message=(
                    "Invalid web_search mode. Use one of: 'lite', 'medium', or 'deep'."
                ),
            ) from exc
    raise ToolCallException(
        message=f"Invalid web search mode type: {type(raw).__name__}",
        llm_facing_message=(
            "Invalid web_search mode. Use 'lite', 'medium', or 'deep'."
        ),
    )


class WebSearchTool(Tool[WebSearchToolOverrideKwargs]):
    NAME = "web_search"
    DESCRIPTION = "Search the web for information."
    DISPLAY_NAME = "Web Search"

    def __init__(self, tool_id: int, emitter: Emitter) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id

        # Get web search provider from database
        with get_session_with_current_tenant() as db_session:
            provider_model = fetch_active_web_search_provider(db_session)
            if provider_model is None:
                raise RuntimeError("No web search provider configured.")
            provider_type = WebSearchProviderType(provider_model.provider_type)
            provider_name = provider_model.name
            api_key = (
                provider_model.api_key.get_value(apply_mask=False)
                if provider_model.api_key
                else None
            )
            config = provider_model.config

        self._provider_type = provider_type
        self._provider_name = provider_name
        self._provider_channel = _get_safe_channel(config)

        if provider_requires_api_key(provider_type) and api_key is None:
            raise RuntimeError(
                f"No API key configured for {provider_type.value} web search provider."
            )

        self._provider = build_search_provider_from_config(
            provider_type=provider_type,
            api_key=api_key,
            config=config,
        )

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def supports_site_filter(self) -> bool:
        """Whether the underlying provider supports site: operator."""
        return self._provider.supports_site_filter

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Available only if an active web search provider is configured in the database."""
        with get_session_with_current_tenant() as session:
            provider = fetch_active_web_search_provider(session)
            return provider is not None

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Search the web for information. Returns a list of search results with titles, metadata, and snippets."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        QUERIES_FIELD: {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "One or more queries to look up on the web. Must contain only printable characters",
                        },
                        MODE_FIELD: {
                            "type": "string",
                            "enum": [mode.value for mode in WebSearchMode],
                            "description": (
                                "Search strength. Use 'lite' for fast, concise freshness checks. "
                                "Use 'medium' for one-shot research on frameworks, projects, products, "
                                "or moderately complex topics. Use 'deep' for higher-recall research, "
                                "fact checking, comparisons, risk, or when source diversity and primary evidence matter."
                            ),
                        },
                    },
                    "required": [QUERIES_FIELD, MODE_FIELD],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=SearchToolStart(is_internet_search=True),
            )
        )

    def _safe_execute_single_search(
        self,
        query: str,
        provider: Any,
    ) -> tuple[list[WebSearchResult] | None, str | None]:
        """Execute a single search query and return results with error capture.

        Returns:
            A tuple of (results, error_message). If successful, error_message is None.
            If failed, results is None and error_message contains the error.
        """
        try:
            raw_results = list(provider.search(query))
            filtered_results = filter_web_search_results_with_no_title_or_snippet(
                raw_results
            )
            results = filtered_results[:DEFAULT_MAX_RESULTS]
            return (results, None)
        except Exception as e:
            error_msg = str(e)
            logger.warning("Web search query '%s' failed: %s", query, error_msg)
            return (None, error_msg)

    def _safe_execute_batch_search(
        self,
        queries: list[str],
        provider: Any,
        mode: WebSearchMode,
    ) -> tuple[list[WebSearchResult] | None, str | None]:
        try:
            raw_results = list(
                provider.search_batch(
                    queries,
                    mode=mode,
                    max_results=DEFAULT_MAX_RESULTS,
                )
            )
            filtered_results = filter_web_search_results_with_no_title_or_snippet(
                raw_results
            )
            return (filtered_results[:DEFAULT_MAX_RESULTS], None)
        except Exception as e:
            error_msg = str(e)
            logger.warning("Batch web search failed: %s", error_msg)
            return (None, error_msg)

    def _emit_debug_delta(
        self,
        *,
        placement: Placement,
        mode: WebSearchMode,
        queries: list[str],
        duration_ms: int,
        results: list[WebSearchResult],
        failed_queries: dict[str, str],
        error: str | None,
    ) -> None:
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=SearchToolDebugDelta(
                    provider_type=self._provider_type.value,
                    provider_name=self._provider_name,
                    mode=mode.value,
                    channel=self._provider_channel,
                    queries=queries,
                    duration_ms=duration_ms,
                    result_count=len(results),
                    results=[
                        SearchToolDebugResult(
                            title=result.title,
                            url=result.link,
                            snippet=result.snippet,
                        )
                        for result in results
                    ],
                    failed_queries=failed_queries,
                    error=error,
                ),
            )
        )

    def run(
        self,
        placement: Placement,
        override_kwargs: WebSearchToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        """Execute the web search tool with multiple queries in parallel"""
        if QUERIES_FIELD not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing required '{QUERIES_FIELD}' parameter in web_search tool call",
                llm_facing_message=(
                    f"The web_search tool requires a '{QUERIES_FIELD}' parameter "
                    f"containing an array of search queries. Please provide the queries "
                    f'like: {{"queries": ["your search query here"]}}'
                ),
            )
        queries = _normalize_queries_input(llm_kwargs[QUERIES_FIELD])
        if not queries:
            raise ToolCallException(
                message=(
                    "No valid web search queries provided; all queries were empty or whitespace-only after trimming."
                ),
                llm_facing_message=(
                    "No valid web search queries were provided (they were empty or "
                    "whitespace-only). Please provide a real search query."
                ),
            )
        mode = _normalize_mode_input(
            llm_kwargs.get(MODE_FIELD),
            override_kwargs.default_mode,
        )

        # Emit queries
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=SearchToolQueriesDelta(queries=queries),
            )
        )

        search_started_at = time.monotonic()

        if getattr(self._provider, "supports_batch_queries", False) is True:
            batch_results, batch_error = self._safe_execute_batch_search(
                queries,
                self._provider,
                mode,
            )
            if batch_error is not None or batch_results is None:
                self._emit_debug_delta(
                    placement=placement,
                    mode=mode,
                    queries=queries,
                    duration_ms=int((time.monotonic() - search_started_at) * 1000),
                    results=[],
                    failed_queries={},
                    error=batch_error,
                )
                raise ToolCallException(
                    message=f"Web search batch failed: {batch_error}",
                    llm_facing_message=(
                        f"Web search failed. Provider error: {batch_error}"
                    ),
                )
            valid_results = [batch_results]
            failed_queries: dict[str, str] = {}
        else:
            # Perform searches in parallel with error capture
            functions_with_args = [
                (self._safe_execute_single_search, (query, self._provider))
                for query in queries
            ]
            search_results_with_errors: list[
                tuple[list[WebSearchResult] | None, str | None]
            ] = run_functions_tuples_in_parallel(
                functions_with_args,
                allow_failures=False,  # Our wrapper handles errors internally
            )

            # Separate successful results from failures
            valid_results = []
            failed_queries = {}

            for query, (results, error) in zip(queries, search_results_with_errors):
                if error is not None:
                    failed_queries[query] = error
                elif results is not None:
                    valid_results.append(results)

        # Log partial failures but continue if we have at least one success
        if failed_queries and valid_results:
            logger.warning(
                "Web search partial failure: %s/%s queries failed. Failed queries: %s",
                len(failed_queries),
                len(queries),
                json.dumps(failed_queries),
            )

        # If all queries failed, raise ToolCallException with details
        if not valid_results:
            error_details = json.dumps(failed_queries, indent=2)
            self._emit_debug_delta(
                placement=placement,
                mode=mode,
                queries=queries,
                duration_ms=int((time.monotonic() - search_started_at) * 1000),
                results=[],
                failed_queries=failed_queries,
                error=error_details,
            )
            raise ToolCallException(
                message=f"All web search queries failed: {error_details}",
                llm_facing_message=(
                    f"All web search queries failed. Query failures:\n{error_details}"
                ),
            )

        # Interweave top results from each query in round-robin fashion
        all_search_results: list[WebSearchResult] = []

        if valid_results:
            # Track seen (title, url) pairs to avoid duplicates
            seen = set()
            # Track current index for each result set
            indices = [0] * len(valid_results)

            # Round-robin interweaving: cycle through result sets and increment indices
            while len(all_search_results) < DEFAULT_MAX_RESULTS:
                added_any = False
                for idx, results in enumerate(valid_results):
                    if len(all_search_results) >= DEFAULT_MAX_RESULTS:
                        break
                    if indices[idx] < len(results):
                        result = results[indices[idx]]
                        key = (result.title, result.link)
                        if key not in seen:
                            seen.add(key)
                            all_search_results.append(result)
                            added_any = True
                        indices[idx] += 1
                # Stop if no more results to add
                if not added_any:
                    break

        duration_ms = int((time.monotonic() - search_started_at) * 1000)
        self._emit_debug_delta(
            placement=placement,
            mode=mode,
            queries=queries,
            duration_ms=duration_ms,
            results=all_search_results,
            failed_queries=failed_queries,
            error=None,
        )

        # This should be a very rare case and is due to not failing loudly enough in the search provider implementation.
        if not all_search_results:
            raise ToolCallException(
                message="Web search queries succeeded but returned no results",
                llm_facing_message=(
                    "Web search completed but found no results for the given queries. "
                    "Try rephrasing or using different search terms."
                ),
            )

        # Convert search results to InferenceSections with rank-based scoring
        inference_sections = [
            inference_section_from_internet_search_result(result, rank=i)
            for i, result in enumerate(all_search_results)
        ]

        # Convert to SearchDocs
        search_docs = convert_inference_sections_to_search_docs(
            inference_sections, is_internet=True
        )

        # Emit documents
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=SearchToolDocumentsDelta(documents=search_docs),
            )
        )

        # Format for LLM
        if not all_search_results:
            docs_str = json.dumps(
                {
                    "results": [],
                    "message": "The web search completed but returned no results for any of the queries. Do not search again.",
                }
            )
            citation_mapping: dict[int, str] = {}
        else:
            docs_str, citation_mapping = convert_inference_sections_to_llm_string(
                top_sections=inference_sections,
                citation_start=override_kwargs.starting_citation_num,
                limit=None,  # Already truncated
                include_source_type=False,
                include_link=True,
            )

        return ToolResponse(
            rich_response=SearchDocsResponse(
                search_docs=search_docs, citation_mapping=citation_mapping
            ),
            llm_facing_response=docs_str,
        )
