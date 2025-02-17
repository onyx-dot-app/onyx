import json
from collections.abc import Generator
from datetime import datetime
from typing import Any
from typing import cast

import httpx

from onyx.chat.chat_utils import combine_message_chain
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import LlmDoc
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.constants import DocumentSource
from onyx.configs.model_configs import GEN_AI_HISTORY_CUTOFF
from onyx.context.search.models import SearchDoc
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.llm.utils import message_to_string
from onyx.prompts.chat_prompts import INTERNET_SEARCH_QUERY_REPHRASE
from onyx.prompts.constants import GENERAL_SEP_PAT
from onyx.secondary_llm_flows.query_expansion import history_based_query_rephrase
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.internet_search.models import (
    InternetSearchResponse,
)
from onyx.tools.tool_implementations.internet_search.models import (
    InternetSearchResult,
)
from onyx.tools.tool_implementations.search_like_tool_utils import (
    build_next_prompt_for_search_like_tool,
)
from onyx.tools.tool_implementations.search_like_tool_utils import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro

logger = setup_logger()

INTERNET_SEARCH_RESPONSE_ID = "internet_search_response"

YES_INTERNET_SEARCH = "Yes Internet Search"
SKIP_INTERNET_SEARCH = "Skip Internet Search"

INTERNET_SEARCH_TEMPLATE = f"""
Given the conversation history and a follow up query, determine if the system should call \
an external internet search tool to better answer the latest user input.
Your default response is {SKIP_INTERNET_SEARCH}.

Respond "{YES_INTERNET_SEARCH}" if:
- The user is asking for information that requires an internet search.

Conversation History:
{GENERAL_SEP_PAT}
{{chat_history}}
{GENERAL_SEP_PAT}

If you are at all unsure, respond with {SKIP_INTERNET_SEARCH}.
Respond with EXACTLY and ONLY "{YES_INTERNET_SEARCH}" or "{SKIP_INTERNET_SEARCH}"

Follow Up Input:
{{final_query}}
""".strip()


def llm_doc_from_internet_search_result(result: InternetSearchResult) -> LlmDoc:
    return LlmDoc(
        document_id=result.link,
        content=result.snippet,
        blurb=result.snippet,
        semantic_identifier=result.link,
        source_type=DocumentSource.WEB,
        metadata={},
        updated_at=datetime.now(),
        link=result.link,
        source_links={0: result.link},
        match_highlights=[],
    )


def internet_search_response_to_search_docs(
    internet_search_response: InternetSearchResponse,
) -> list[SearchDoc]:
    return [
        SearchDoc(
            document_id=doc.link,
            chunk_ind=-1,
            semantic_identifier=doc.title,
            link=doc.link,
            blurb=doc.snippet,
            source_type=DocumentSource.NOT_APPLICABLE,
            boost=0,
            hidden=False,
            metadata={},
            score=None,
            match_highlights=[],
            updated_at=None,
            primary_owners=[],
            secondary_owners=[],
            is_internet=True,
        )
        for doc in internet_search_response.internet_results
    ]


# override_kwargs is not supported for internet search tools
class InternetSearchTool(Tool[None]):
    _NAME = "run_internet_search"
    _DISPLAY_NAME = "Internet Search"
    _DESCRIPTION = "Perform an internet search for up-to-date information."

    def __init__(
        self,
        api_key: str,
        answer_style_config: AnswerStyleConfig,
        prompt_config: PromptConfig,
        num_results: int = 10,
    ) -> None:
        self.api_key = api_key
        self.answer_style_config = answer_style_config
        self.prompt_config = prompt_config

        self.host = "https://api.bing.microsoft.com/v7.0"
        self.headers = {
            "Ocp-Apim-Subscription-Key": api_key,
            "Content-Type": "application/json",
        }
        self.num_results = num_results
        self.client = httpx.Client()

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "internet_search_query": {
                            "type": "string",
                            "description": "Query to search on the internet",
                        },
                    },
                    "required": ["internet_search_query"],
                },
            },
        }

    def check_if_needs_internet_search(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
    ) -> bool:
        history_str = combine_message_chain(
            messages=history, token_limit=GEN_AI_HISTORY_CUTOFF
        )
        prompt = INTERNET_SEARCH_TEMPLATE.format(
            chat_history=history_str,
            final_query=query,
        )
        use_internet_search_output = message_to_string(llm.invoke(prompt))

        logger.debug(
            f"Evaluated if should use internet search: {use_internet_search_output}"
        )

        return (
            YES_INTERNET_SEARCH.split()[0]
        ).lower() in use_internet_search_output.lower()

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        if not force_run and not self.check_if_needs_internet_search(
            query, history, llm
        ):
            return None

        rephrased_query = history_based_query_rephrase(
            query=query,
            history=history,
            llm=llm,
            prompt_template=INTERNET_SEARCH_QUERY_REPHRASE,
        )
        return {
            "internet_search_query": rephrased_query,
        }

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        search_response = cast(InternetSearchResponse, args[0].response)
        return json.dumps(search_response.model_dump())

    def _perform_search(self, query: str) -> InternetSearchResponse:
        response = self.client.get(
            f"{self.host}/search",
            headers=self.headers,
            params={"q": query, "count": self.num_results},
        )

        response.raise_for_status()

        results = response.json()

        # If no hits, Bing does not include the webPages key
        search_results = (
            results["webPages"]["value"][: self.num_results]
            if "webPages" in results
            else []
        )

        return InternetSearchResponse(
            revised_query=query,
            internet_results=[
                InternetSearchResult(
                    title=result["name"],
                    link=result["url"],
                    snippet=result["snippet"],
                )
                for result in search_results
            ],
        )

    def run(
        self, override_kwargs: None = None, **kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        query = cast(str, kwargs["internet_search_query"])

        results = self._perform_search(query)
        yield ToolResponse(
            id=INTERNET_SEARCH_RESPONSE_ID,
            response=results,
        )

        llm_docs = [
            llm_doc_from_internet_search_result(result)
            for result in results.internet_results
        ]

        yield ToolResponse(
            id=FINAL_CONTEXT_DOCUMENTS_ID,
            response=llm_docs,
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        search_response = cast(InternetSearchResponse, args[0].response)
        return search_response.model_dump()

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        return build_next_prompt_for_search_like_tool(
            prompt_builder=prompt_builder,
            tool_call_summary=tool_call_summary,
            tool_responses=tool_responses,
            using_tool_calling_llm=using_tool_calling_llm,
            answer_style_config=self.answer_style_config,
            prompt_config=self.prompt_config,
            context_type="internet search results",
        )
