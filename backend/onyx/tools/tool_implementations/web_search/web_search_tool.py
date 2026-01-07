import json
import re
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
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.interface import Tool
from onyx.tools.models import ToolResponse
from onyx.tools.models import WebSearchToolOverrideKwargs
from onyx.tools.tool_implementations.utils import (
    convert_inference_sections_to_llm_string,
)
from onyx.tools.tool_implementations.web_search.clients.exa_client import ExaClient
from onyx.tools.tool_implementations.web_search.models import DEFAULT_MAX_RESULTS
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
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

    def _transform_queries_for_provider(
        self, queries: list[str]
    ) -> tuple[list[str], dict[str, list[str]]]:
        """Transform queries for provider-specific requirements.

        For Exa: extracts domains from site: operators and converts to include_domains format.
        For other providers: returns queries as-is (they support site: natively).

        Returns:
            Tuple of (transformed_queries, query_domains_map) where query_domains_map
            maps cleaned query -> list of domains for Exa's include_domains parameter.
        """
        query_domains_map: dict[str, list[str]] = {}

        if not isinstance(self._provider, ExaClient):
            return queries, query_domains_map

        cleaned_queries = []
        for query in queries:
            # Extract domains from site: operators
            site_domains = re.findall(r"site:\s*([^\s]+)", query, re.IGNORECASE)

            # Remove site: operator for Exa
            cleaned_query = re.sub(
                r"site:\s*\S+\s*", "", query, flags=re.IGNORECASE
            ).strip()
            if not cleaned_query and site_domains:
                cleaned_query = site_domains[0]

            # Normalize and store domains for this query
            if site_domains:
                normalized_domains = [
                    domain.lower().split("/")[0].removeprefix("www.")
                    for domain in site_domains
                ]
                query_domains_map[cleaned_query] = normalized_domains

            cleaned_queries.append(cleaned_query)

        return cleaned_queries if cleaned_queries else queries, query_domains_map

    def _execute_single_search(
        self,
        query: str,
        provider: Any,
        include_domains: list[str] | None = None,
    ) -> list[WebSearchResult]:
        """Execute a single search query and return results."""
        if include_domains:
            # Try with domain restriction first (Exa's recommended approach)
            results = list(provider.search(query, include_domains=include_domains))[
                :DEFAULT_MAX_RESULTS
            ]
            # Fallback: if domain-restricted search returns no results, try without restriction
            if results:
                return results
        return list(provider.search(query))[:DEFAULT_MAX_RESULTS]

    def run(
        self,
        placement: Placement,
        override_kwargs: WebSearchToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        """Execute the web search tool with multiple queries in parallel"""
        queries = cast(list[str], llm_kwargs[QUERIES_FIELD])
        queries, query_domains_map = self._transform_queries_for_provider(queries)

        # Emit queries
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=SearchToolQueriesDelta(queries=queries),
            )
        )

        # Perform searches in parallel
        functions_with_args = [
            (
                self._execute_single_search,
                (query, self._provider, query_domains_map.get(query)),
            )
            for query in queries
        ]
        search_results_per_query: list[list[WebSearchResult]] = (
            run_functions_tuples_in_parallel(
                functions_with_args,
                allow_failures=True,
            )
        )

        # Interweave top results from each query in round-robin fashion
        # Filter out None results from failures
        valid_results = [
            results for results in search_results_per_query if results is not None
        ]
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

        # Emit SectionEnd to signal search completion
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=SectionEnd(),
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
