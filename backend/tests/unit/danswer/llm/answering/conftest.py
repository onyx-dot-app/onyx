import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import SystemMessage

from danswer.chat.models import LlmDoc
from danswer.configs.constants import DocumentSource
from danswer.llm.answering.models import AnswerStyleConfig
from danswer.llm.answering.models import CitationConfig
from danswer.llm.answering.models import PromptConfig
from danswer.llm.answering.prompts.build import AnswerPromptBuilder
from danswer.llm.interfaces import LLMConfig
from danswer.tools.models import ToolResponse
from danswer.tools.tool_implementations.search.search_tool import SearchTool
from danswer.tools.tool_implementations.search_like_tool_utils import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)

QUERY = "Test question"
DEFAULT_SEARCH_ARGS = {"query": "search"}


@pytest.fixture
def answer_style_config() -> AnswerStyleConfig:
    return AnswerStyleConfig(citation_config=CitationConfig())


@pytest.fixture
def prompt_config() -> PromptConfig:
    return PromptConfig(
        system_prompt="System prompt",
        task_prompt="Task prompt",
        datetime_aware=False,
        include_citations=True,
    )


@pytest.fixture
def mock_llm() -> MagicMock:
    mock_llm_obj = MagicMock()
    mock_llm_obj.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-4o",
        temperature=0.0,
        api_key=None,
        api_base=None,
        api_version=None,
    )
    return mock_llm_obj


@pytest.fixture
def mock_search_results() -> list[LlmDoc]:
    return [
        LlmDoc(
            content="Search result 1",
            source_type=DocumentSource.WEB,
            metadata={"id": "doc1"},
            document_id="doc1",
            blurb="Blurb 1",
            semantic_identifier="Semantic ID 1",
            updated_at=datetime(2023, 1, 1),
            link="https://example.com/doc1",
            source_links={0: "https://example.com/doc1"},
        ),
        LlmDoc(
            content="Search result 2",
            source_type=DocumentSource.WEB,
            metadata={"id": "doc2"},
            document_id="doc2",
            blurb="Blurb 2",
            semantic_identifier="Semantic ID 2",
            updated_at=datetime(2023, 1, 2),
            link="https://example.com/doc2",
            source_links={0: "https://example.com/doc2"},
        ),
    ]


@pytest.fixture
def mock_search_tool(mock_search_results: list[LlmDoc]) -> MagicMock:
    mock_tool = MagicMock(spec=SearchTool)
    mock_tool.name = "search"
    mock_tool.build_tool_message_content.return_value = "search_response"
    mock_tool.get_args_for_non_tool_calling_llm.return_value = DEFAULT_SEARCH_ARGS
    mock_tool.final_result.return_value = [
        json.loads(doc.model_dump_json()) for doc in mock_search_results
    ]
    mock_tool.run.return_value = [
        ToolResponse(id=FINAL_CONTEXT_DOCUMENTS_ID, response=mock_search_results)
    ]
    mock_tool.tool_definition.return_value = {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search for information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                },
                "required": ["query"],
            },
        },
    }
    mock_post_search_tool_prompt_builder = MagicMock(spec=AnswerPromptBuilder)
    mock_post_search_tool_prompt_builder.build.return_value = [
        SystemMessage(content="Updated system prompt"),
    ]
    mock_tool.build_next_prompt.return_value = mock_post_search_tool_prompt_builder
    return mock_tool
