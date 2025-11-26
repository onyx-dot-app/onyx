from collections.abc import Generator
from collections.abc import Sequence
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebContentProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
    get_default_content_provider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    dummy_inference_section_from_internet_content,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    truncate_search_result_content,
)
from onyx.chat.models import DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.chat.turn.models import FetchedDocumentCacheEntry
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.web_search import fetch_active_web_search_provider
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.server.query_and_chat.streaming_models import FetchToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SavedSearchDoc
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import RunContextWrapper
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
from onyx.tools.tool_result_models import LlmOpenUrlResult
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


logger = setup_logger()

_OPEN_URL_GENERIC_ERROR_MESSAGE = (
    "OpenUrlTool should only be used by the Deep Research Agent, not via tool calling."
)


class OpenUrlTool(Tool[None]):
    _NAME = "open_url"
    _DESCRIPTION = "Fetch and extract full content from web pages."
    _DISPLAY_NAME = "Open URL"

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
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "URLs to fetch content from",
                        },
                    },
                    "required": ["urls"],
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
        raise ValueError(_OPEN_URL_GENERIC_ERROR_MESSAGE)

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        raise ValueError(_OPEN_URL_GENERIC_ERROR_MESSAGE)

    @tool_accounting
    def _open_url_core(
        self,
        run_context: RunContextWrapper[Any],
        urls: Sequence[str],
        content_provider: WebContentProvider,
    ) -> list[LlmOpenUrlResult]:
        # TODO: Find better way to track index that isn't so implicit
        # based on number of tool calls
        index = run_context.context.current_run_step

        # Create SavedSearchDoc objects from URLs for the FetchToolStart event
        saved_search_docs = [SavedSearchDoc.from_url(url) for url in urls]

        run_context.context.run_dependencies.emitter.emit(
            Packet(
                ind=index,
                obj=FetchToolStart(
                    type="fetch_tool_start", documents=saved_search_docs
                ),
            )
        )

        docs = content_provider.contents(urls)
        results = [
            LlmOpenUrlResult(
                document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                content=truncate_search_result_content(doc.full_content),
                unique_identifier_to_strip_away=doc.link,
            )
            for doc in docs
        ]
        for doc in docs:
            cache = run_context.context.fetched_documents_cache
            entry = cache.setdefault(
                doc.link,
                FetchedDocumentCacheEntry(
                    inference_section=dummy_inference_section_from_internet_content(
                        doc
                    ),
                    document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                ),
            )
            entry.inference_section = dummy_inference_section_from_internet_content(doc)
        run_context.context.iteration_instructions.append(
            IterationInstructions(
                iteration_nr=index,
                plan="plan",
                purpose="Fetching content from URLs",
                reasoning=f"I am now using Web Fetch to gather information on {', '.join(urls)}",
            )
        )
        from onyx.db.tools import get_tool_by_name
        from onyx.tools.tool_implementations.web_search.web_search_tool import (
            WebSearchTool,
        )

        run_context.context.global_iteration_responses.append(
            IterationAnswer(
                # TODO: For now, we're using the web_search_tool_name since the web_fetch_tool_name is not a built-in tool
                tool=WebSearchTool.__name__,
                tool_id=get_tool_by_name(
                    WebSearchTool.__name__,
                    run_context.context.run_dependencies.db_session,
                ).id,
                iteration_nr=index,
                parallelization_nr=0,
                question=f"Fetch content from URLs: {', '.join(urls)}",
                reasoning=f"I am now using Web Fetch to gather information on {', '.join(urls)}",
                answer="",
                cited_documents={
                    i: dummy_inference_section_from_internet_content(d)
                    for i, d in enumerate(docs)
                },
                claims=[],
                is_web_fetch=True,
            )
        )

        # Set flag to include citation requirements since we fetched documents
        run_context.context.should_cite_documents = True

        return results

    def run_v2(
        self,
        run_context: RunContextWrapper[Any],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Run open_url using the v2 implementation"""
        urls = kwargs.get("urls", [])
        if not urls:
            raise ValueError("urls parameter is required")

        content_provider = get_default_content_provider()
        if content_provider is None:
            raise ValueError("No web content provider found")

        retrieved_docs = self._open_url_core(run_context, urls, content_provider)  # type: ignore[arg-type]
        adapter = TypeAdapter(list[LlmOpenUrlResult])
        return adapter.dump_json(retrieved_docs).decode()

    def run(
        self, override_kwargs: None = None, **llm_kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        raise ValueError(_OPEN_URL_GENERIC_ERROR_MESSAGE)

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        raise ValueError(_OPEN_URL_GENERIC_ERROR_MESSAGE)

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        raise ValueError(_OPEN_URL_GENERIC_ERROR_MESSAGE)
