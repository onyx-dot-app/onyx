import json
from typing import Any

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.context.search.models import SearchDocsResponse
from onyx.context.search.utils import convert_inference_sections_to_search_docs
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.web_search import fetch_active_web_search_provider
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.tools.constants import WEB_SEARCH_TOOL_NAME
from onyx.tools.interface import (
    CITATIONS_PER_TOOL_CALL,
    Tool,
    parse_tool_arguments,
    tool_definition_from_arguments,
)
from onyx.tools.models import (
    CodeModeExposure,
    CodeModeResultSpec,
    SearchResults,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.utils import (
    SEARCH_RESULTS_CODE_MODE_RESULT,
    convert_inference_sections_to_llm_string,
)
from onyx.tools.tool_implementations.web_search.models import (
    DEFAULT_MAX_RESULTS,
    WebSearchArguments,
    WebSearchResult,
)
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
    provider_requires_api_key,
)
from onyx.tools.tool_implementations.web_search.utils import (
    filter_web_search_results_with_no_title_or_snippet,
    inference_section_from_internet_search_result,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from shared_configs.enums import WebSearchProviderType

logger = setup_logger()


class WebSearchTool(Tool):
    merge_list_argument = "queries"

    NAME = WEB_SEARCH_TOOL_NAME
    DESCRIPTION = "Search the web for information."
    DISPLAY_NAME = "Web Search"

    def __init__(self, tool_id: int) -> None:
        self._id = tool_id

        # Get web search provider from database
        with get_session_with_current_tenant() as db_session:
            provider_model = fetch_active_web_search_provider(db_session)
            if provider_model is None:
                raise RuntimeError("No web search provider configured.")
            provider_type = WebSearchProviderType(provider_model.provider_type)
            api_key = (
                provider_model.api_key.get_value(apply_mask=False)
                if provider_model.api_key
                else None
            )
            config = provider_model.config

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
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.IMMEDIATE

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
    def code_mode_result(self) -> CodeModeResultSpec:
        return SEARCH_RESULTS_CODE_MODE_RESULT

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

    def tool_definition(self) -> ToolDefinition:
        return tool_definition_from_arguments(
            self.name,
            "Search the web for information. Returns a list of search results with titles, metadata, and snippets.",
            WebSearchArguments,
            strict=True,
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

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        queries = parse_tool_arguments(WebSearchArguments, invocation.arguments).queries

        invocation.update(
            ToolProgress(
                details=SearchDocsResponse(
                    search_docs=[], citation_mapping={}, queries=queries
                )
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

        for query, (results, error) in zip(
            queries, search_results_with_errors, strict=True
        ):
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
        invocation.update(
            ToolProgress(
                details=SearchDocsResponse(
                    search_docs=search_docs,
                    citation_mapping={},
                    queries=queries,
                )
            )
        )

        # Format for LLM
        if not all_search_results:
            docs_str = SearchResults(
                results=[],
                message="The web search completed but returned no results for any of the queries. Do not search again.",
            ).model_dump_json()
            citation_mapping: dict[int, str] = {}
        else:
            docs_str, citation_mapping = convert_inference_sections_to_llm_string(
                top_sections=inference_sections,
                citation_start=context.next_citation_num
                + CITATIONS_PER_TOOL_CALL * invocation.call_index,
                limit=None,  # Already truncated
                include_source_type=False,
                include_link=True,
            )

        return ToolResult(
            details=SearchDocsResponse(
                search_docs=search_docs,
                citation_mapping=citation_mapping,
                queries=queries,
            ),
            content=docs_str,
        )
