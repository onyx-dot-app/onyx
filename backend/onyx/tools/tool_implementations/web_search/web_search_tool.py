import json
from typing import Any
from typing import cast

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.context.search.models import SearchDocsResponse
from onyx.context.search.utils import convert_inference_sections_to_search_docs
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.web_search import fetch_active_web_search_provider
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
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
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
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
            api_key = provider_model.api_key
            config = provider_model.config

        # TODO - This should just be enforced at the DB level
        if api_key is None:
            raise RuntimeError("No API key configured for web search provider.")

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
                            "description": "One or more queries to look up on the web.",
                        },
                    },
                    "required": [QUERIES_FIELD],
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
            logger.warning(f"Web search query '{query}' failed: {error_msg}")
            return (None, error_msg)

    def run(
        self,
        placement: Placement,
        override_kwargs: WebSearchToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        """Execute the web search tool with multiple queries in parallel"""
        queries = cast(list[str], llm_kwargs[QUERIES_FIELD])

        # Emit queries
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=SearchToolQueriesDelta(queries=queries),
            )
        )

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
        valid_results: list[list[WebSearchResult]] = []
        failed_queries: dict[str, str] = {}

        for query, (results, error) in zip(queries, search_results_with_errors):
            if error is not None:
                failed_queries[query] = error
            elif results is not None:
                valid_results.append(results)

        # Log partial failures but continue if we have at least one success
        if failed_queries and valid_results:
            logger.warning(
                f"Web search partial failure: {len(failed_queries)}/{len(queries)} "
                f"queries failed. Failed queries: {json.dumps(failed_queries)}"
            )

        # If all queries failed, raise ToolCallException with details
        if not valid_results:
            error_details = json.dumps(failed_queries, indent=2)
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
