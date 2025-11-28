import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from onyx.chat.chat_utils import llm_doc_from_inference_section
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import CitationConfig
from onyx.chat.models import LlmDoc
from onyx.chat.models import PromptConfig
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SearchDoc
from onyx.context.search.models import SearchDocsResponse
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.utils import get_max_input_tokens
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.search.search_tool import SearchTool

QUERY = "Test question"
DEFAULT_SEARCH_ARGS = {"query": "search"}


@pytest.fixture
def answer_style_config() -> AnswerStyleConfig:
    return AnswerStyleConfig(citation_config=CitationConfig())


@pytest.fixture
def prompt_config() -> PromptConfig:
    return PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions="System prompt",
        reminder="Task prompt",
        datetime_aware=False,
    )


@pytest.fixture
def mock_llm() -> MagicMock:
    model_provider = "openai"
    model_name = "gpt-4o"

    mock_llm_obj = MagicMock(spec=LLM)
    mock_llm_obj.config = LLMConfig(
        model_provider=model_provider,
        model_name=model_name,
        temperature=0.0,
        api_key=None,
        api_base=None,
        api_version=None,
        max_input_tokens=get_max_input_tokens(
            model_provider=model_provider,
            model_name=model_name,
        ),
    )
    return mock_llm_obj


@pytest.fixture
def mock_inference_sections() -> list[InferenceSection]:
    return [
        InferenceSection(
            combined_content="Search result 1",
            center_chunk=InferenceChunk(
                chunk_id=1,
                section_continuation=False,
                title=None,
                boost=1,
                recency_bias=0.5,
                score=1.0,
                hidden=False,
                content="Search result 1",
                source_type=DocumentSource.WEB,
                metadata={"id": "doc1"},
                document_id="doc1",
                blurb="Blurb 1",
                semantic_identifier="Semantic ID 1",
                updated_at=datetime(2023, 1, 1),
                source_links={0: "https://example.com/doc1"},
                match_highlights=[],
                image_file_id=None,
                doc_summary="",
                chunk_context="",
            ),
            chunks=MagicMock(),
        ),
        InferenceSection(
            combined_content="Search result 2",
            center_chunk=InferenceChunk(
                chunk_id=2,
                section_continuation=False,
                title=None,
                boost=1,
                recency_bias=0.5,
                score=1.0,
                hidden=False,
                content="Search result 2",
                source_type=DocumentSource.WEB,
                metadata={"id": "doc2"},
                document_id="doc2",
                blurb="Blurb 2",
                semantic_identifier="Semantic ID 2",
                updated_at=datetime(2023, 1, 2),
                source_links={0: "https://example.com/doc2"},
                match_highlights=[],
                image_file_id=None,
                doc_summary="",
                chunk_context="",
            ),
            chunks=MagicMock(),
        ),
    ]


@pytest.fixture
def mock_search_results(
    mock_inference_sections: list[InferenceSection],
) -> list[LlmDoc]:
    return [
        llm_doc_from_inference_section(section) for section in mock_inference_sections
    ]


@pytest.fixture
def mock_search_tool(mock_search_results: list[LlmDoc]) -> MagicMock:
    mock_tool = MagicMock(spec=SearchTool)
    # Make type().__name__ return "SearchTool" for prompt builder checks
    type(mock_tool).__name__ = "SearchTool"
    mock_tool.name = "search"
    mock_tool.description = "Search for information"
    mock_tool.get_llm_tool_response.return_value = "search_response"
    mock_tool.final_result.return_value = [
        json.loads(doc.model_dump_json()) for doc in mock_search_results
    ]
    # Convert LlmDoc objects to SearchDoc objects
    search_docs = [
        SearchDoc(
            document_id=doc.document_id,
            chunk_ind=0,  # Default value
            semantic_identifier=doc.semantic_identifier,
            link=doc.link,
            blurb=doc.blurb,
            source_type=doc.source_type,
            boost=0,  # Default value
            hidden=False,  # Default value
            metadata=doc.metadata,
            score=None,  # Default value
            match_highlights=doc.match_highlights or [],
            updated_at=doc.updated_at,
            primary_owners=None,  # Default value
            secondary_owners=None,  # Default value
            is_internet=False,  # Default value
        )
        for doc in mock_search_results
    ]
    # Create citation mapping (1-indexed citations)
    citation_mapping = {
        i + 1: doc.document_id for i, doc in enumerate(mock_search_results)
    }
    # Create a simple LLM-facing response string
    llm_facing_response = "\n\n".join(
        f"[{i+1}] {doc.content}" for i, doc in enumerate(mock_search_results)
    )
    mock_tool.run.return_value = ToolResponse(
        rich_response=SearchDocsResponse(
            search_docs=search_docs, citation_mapping=citation_mapping
        ),
        llm_facing_response=llm_facing_response,
    )
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
    return mock_tool
