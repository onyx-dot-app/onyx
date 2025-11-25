from collections.abc import Generator
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchResult,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
    get_default_provider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    dummy_inference_section_from_internet_search_result,
)
from onyx.chat.models import DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.chat.turn.models import FetchedDocumentCacheEntry
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.web_search import fetch_active_web_search_provider
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import RunContextWrapper
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
from onyx.tools.tool_result_models import LlmWebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro
from onyx.utils.threadpool_concurrency import FunctionCall
from onyx.utils.threadpool_concurrency import run_functions_in_parallel


logger = setup_logger()

# TODO: Align on separation of Tools and SubAgents. Right now, we're only keeping this around for backwards compatibility.
QUERY_FIELD = "query"
_GENERIC_ERROR_MESSAGE = "WebSearchTool should only be used by the Deep Research Agent, not via tool calling."
_OPEN_URL_GENERIC_ERROR_MESSAGE = (
    "OpenUrlTool should only be used by the Deep Research Agent, not via tool calling."
)


class WebSearchTool(Tool[None]):
    _NAME = "run_web_search"
    _DESCRIPTION = "Search the web for information."
    _DISPLAY_NAME = "Web Search"

    def __init__(self, tool_id: int) -> None:
        self._id = tool_id

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

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
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        QUERY_FIELD: {
                            "type": "string",
                            "description": "What to search for",
                        },
                    },
                    "required": [QUERY_FIELD],
                },
            },
        }

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    @tool_accounting
    def _web_search_core(
        self,
        run_context: RunContextWrapper[Any],
        queries: list[str],
        search_provider: WebSearchProvider,
    ) -> list[LlmWebSearchResult]:
        index = run_context.context.current_run_step
        run_context.context.run_dependencies.emitter.emit(
            Packet(
                ind=index,
                obj=SearchToolStart(
                    type="internal_search_tool_start", is_internet_search=True
                ),
            )
        )

        # Emit a packet in the beginning to communicate queries to the frontend
        run_context.context.run_dependencies.emitter.emit(
            Packet(
                ind=index,
                obj=SearchToolDelta(
                    type="internal_search_tool_delta",
                    queries=queries,
                    documents=[],
                ),
            )
        )

        queries_str = ", ".join(queries)
        run_context.context.iteration_instructions.append(
            IterationInstructions(
                iteration_nr=index,
                plan="plan",
                purpose="Searching the web for information",
                reasoning=f"I am now using Web Search to gather information on {queries_str}",
            )
        )

        # Search all queries in parallel
        function_calls = [
            FunctionCall(func=search_provider.search, args=(query,))
            for query in queries
        ]
        search_results_dict = run_functions_in_parallel(function_calls)

        # Aggregate all results from all queries
        all_hits: list[WebSearchResult] = []
        for result_id in search_results_dict:
            hits = search_results_dict[result_id]
            if hits:
                all_hits.extend(hits)

        inference_sections = [
            dummy_inference_section_from_internet_search_result(r) for r in all_hits
        ]

        from onyx.agents.agent_search.dr.utils import (
            convert_inference_sections_to_search_docs,
        )

        saved_search_docs = convert_inference_sections_to_search_docs(
            inference_sections, is_internet=True
        )

        run_context.context.run_dependencies.emitter.emit(
            Packet(
                ind=index,
                obj=SearchToolDelta(
                    type="internal_search_tool_delta",
                    queries=queries,
                    documents=saved_search_docs,
                ),
            )
        )

        results = []
        for r in all_hits:
            results.append(
                LlmWebSearchResult(
                    document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                    url=r.link,
                    title=r.title,
                    snippet=r.snippet or "",
                    unique_identifier_to_strip_away=r.link,
                )
            )
            if r.link not in run_context.context.fetched_documents_cache:
                run_context.context.fetched_documents_cache[r.link] = (
                    FetchedDocumentCacheEntry(
                        inference_section=dummy_inference_section_from_internet_search_result(
                            r
                        ),
                        document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                    )
                )

        from onyx.db.tools import get_tool_by_name

        run_context.context.global_iteration_responses.append(
            IterationAnswer(
                tool=WebSearchTool.__name__,
                tool_id=get_tool_by_name(
                    WebSearchTool.__name__,
                    run_context.context.run_dependencies.db_session,
                ).id,
                iteration_nr=index,
                parallelization_nr=0,
                question=queries_str,
                reasoning=f"I am now using Web Search to gather information on {queries_str}",
                answer="",
                cited_documents={
                    i: inference_section
                    for i, inference_section in enumerate(inference_sections)
                },
                claims=[],
                queries=queries,
            )
        )
        run_context.context.should_cite_documents = True
        return results

    def run_v2(
        self,
        run_context: RunContextWrapper[Any],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Run web search using the v2 implementation"""
        queries = kwargs.get("queries", [])
        if not queries:
            raise ValueError("queries parameter is required")

        search_provider = get_default_provider()
        if search_provider is None:
            raise ValueError("No search provider found")

        response = self._web_search_core(run_context, queries, search_provider)  # type: ignore[arg-type]
        adapter = TypeAdapter(list[LlmWebSearchResult])
        return adapter.dump_json(response).decode()

    def run(
        self, override_kwargs: None = None, **llm_kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        raise ValueError(_GENERIC_ERROR_MESSAGE)
