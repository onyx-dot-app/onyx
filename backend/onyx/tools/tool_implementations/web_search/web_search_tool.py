import json
from typing import Any
from typing import cast

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.infra import Emitter
from onyx.context.search.models import SearchDocsResponse
from onyx.context.search.utils import convert_inference_sections_to_search_docs
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.web_search import fetch_active_web_search_provider
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.search.search_tool import (
    _convert_inference_sections_to_llm_string,
)
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
)
from onyx.tools.tool_implementations.web_search.utils import (
    dummy_inference_section_from_internet_search_result,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

QUERY_FIELD = "query"
DEFAULT_MAX_RESULTS = 10


class WebSearchTool(Tool[None]):
    _NAME = "web_search"
    _DESCRIPTION = "Search the web for information."
    _DISPLAY_NAME = "Web Search"

    def __init__(self, tool_id: int, emitter: Emitter) -> None:
        super().__init__(emitter=emitter)
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

    def emit_start(self, turn_index: int, tab_index: int) -> None:
        self.emitter.emit(
            Packet(
                turn_index=turn_index,
                tab_index=tab_index,
                obj=SearchToolStart(is_internet_search=True),
            )
        )

    def run(
        self,
        turn_index: int,
        tab_index: int,
        override_kwargs: None,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        """Execute the web search tool"""
        query = cast(str, llm_kwargs[QUERY_FIELD])

        # Get web search provider from database
        with get_session_with_current_tenant() as db_session:
            provider_model = fetch_active_web_search_provider(db_session)
            if provider_model is None:
                error_msg = "No web search provider configured."
                logger.error(error_msg)
                error_result = {"error": error_msg}
                llm_facing_response = json.dumps(error_result)

                return ToolResponse(
                    rich_response=SearchDocsResponse(
                        search_docs=[], citation_mapping={}
                    ),
                    llm_facing_response=llm_facing_response,
                )

            # Build provider from config
            from shared_configs.enums import WebSearchProviderType

            try:
                provider = build_search_provider_from_config(
                    provider_type=WebSearchProviderType(provider_model.provider_type),
                    api_key=provider_model.api_key,
                    config=provider_model.config or {},
                )
            except Exception as e:
                error_msg = f"Failed to initialize web search provider: {str(e)}"
                logger.error(error_msg)
                error_result = {"error": error_msg}
                llm_facing_response = json.dumps(error_result)

                return ToolResponse(
                    rich_response=SearchDocsResponse(
                        search_docs=[], citation_mapping={}
                    ),
                    llm_facing_response=llm_facing_response,
                )

            if provider is None:
                error_msg = "Unable to initialize the configured web search provider."
                logger.error(error_msg)
                error_result = {"error": error_msg}
                llm_facing_response = json.dumps(error_result)

                return ToolResponse(
                    rich_response=SearchDocsResponse(
                        search_docs=[], citation_mapping={}
                    ),
                    llm_facing_response=llm_facing_response,
                )

        # Emit queries
        queries = [query]
        self.emitter.emit(
            Packet(
                turn_index=turn_index,
                tab_index=tab_index,
                obj=SearchToolQueriesDelta(queries=queries),
            )
        )

        # Perform search
        try:
            search_results = list(provider.search(query))[:DEFAULT_MAX_RESULTS]
        except Exception as e:
            error_msg = f"Web search failed: {str(e)}"
            logger.error(error_msg)
            error_result = {"error": error_msg}
            llm_facing_response = json.dumps(error_result)

            return ToolResponse(
                rich_response=SearchDocsResponse(search_docs=[], citation_mapping={}),
                llm_facing_response=llm_facing_response,
            )

        # Convert search results to InferenceSections
        inference_sections = [
            dummy_inference_section_from_internet_search_result(result)
            for result in search_results
        ]

        # Convert to SearchDocs
        search_docs = convert_inference_sections_to_search_docs(
            inference_sections, is_internet=True
        )

        # Emit documents
        self.emitter.emit(
            Packet(
                turn_index=turn_index,
                tab_index=tab_index,
                obj=SearchToolDocumentsDelta(documents=search_docs),
            )
        )

        # Format for LLM
        docs_str, citation_mapping = _convert_inference_sections_to_llm_string(
            top_sections=inference_sections,
            citation_start=1,
            limit=None,
        )

        return ToolResponse(
            rich_response=SearchDocsResponse(
                search_docs=search_docs, citation_mapping=citation_mapping
            ),
            llm_facing_response=docs_str,
        )
