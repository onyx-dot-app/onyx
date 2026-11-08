import json

from onyx.chat.prompt_utils import prepare_prompt
from onyx.chat.tool_results import tool_result_sources
from onyx.context.search.models import SearchDocsResponse
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.llm.models import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from onyx.tools.models import CustomToolCallSummary, GeneratedImage
from onyx.tools.tool_implementations.code_mode.models import (
    CodeModeCall,
    CodeModeExecutionResult,
)
from onyx.tools.tool_implementations.code_mode.prompt import format_content
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from tests.unit.onyx.tools.code_mode.fakes import search_doc

DOC_A = search_doc("alpha")
DOC_B = search_doc("beta")


def test_search_results_show_their_displayed_documents_and_resolve_citations() -> None:
    sources = tool_result_sources(
        SearchDocsResponse(
            search_docs=[DOC_A, DOC_B],
            displayed_docs=[DOC_B],
            citation_mapping={3: "alpha", 4: "missing"},
        )
    )
    assert sources is not None
    assert sources.documents == [DOC_A, DOC_B]
    assert sources.displayed == [DOC_B]
    assert sources.citations == {3: DOC_A}


def test_program_results_merge_the_documents_of_their_searches() -> None:
    search = CodeModeCall(
        id="code:0",
        index=0,
        tool_name="web_search",
        function_name="web_search",
        arguments={},
        state="ok",
        details=SearchDocsResponse(
            search_docs=[DOC_A], displayed_docs=[DOC_B], citation_mapping={1: "alpha"}
        ),
    )
    sources = tool_result_sources(
        CodeModeExecutionResult(cell_id=1, status="completed", calls=[search])
    )
    assert sources is not None
    assert sources.documents == [DOC_A, DOC_B]
    assert sources.citations == {1: DOC_A}


def test_research_results_cite_documents_without_showing_them() -> None:
    sources = tool_result_sources(
        ResearchAgentCallResult(
            intermediate_report="report", citation_mapping={5: DOC_B}
        )
    )
    assert sources is not None
    assert (sources.documents, sources.citations) == ([DOC_B], {5: DOC_B})
    assert sources.displayed is None


def test_results_without_documents_have_no_sources() -> None:
    custom = CustomToolCallSummary(
        tool_name="lookup", response_type="json", tool_result={"value": 1}
    )
    assert tool_result_sources(custom) is None
    assert tool_result_sources(None) is None


def test_later_prompts_replay_program_observations_with_their_images() -> None:
    image = GeneratedImage(
        file_id="image-1", url="/api/chat/file/image-1", revised_prompt="a red fox"
    )
    details = CodeModeExecutionResult(
        cell_id=1,
        code="await generate_image(prompt='fox')",
        status="completed",
        calls=[
            CodeModeCall(
                id="code:0",
                state="ok",
                index=0,
                tool_name="generate_image",
                function_name="generate_image",
                arguments={"prompt": "fox"},
                details=FinalImageGenerationResponse(generated_images=[image]),
            )
        ],
    )
    content = format_content(
        details,
        cell_calls=details.calls,
        max_tokens=1_000,
        end=None,
        discarded=None,
        elided_chars=0,
    )
    references = [{"file_id": "image-1", "revised_prompt": "a red fox"}]
    assert content.endswith(f"Generated images: {json.dumps(references)}")
    program = ToolResultMessage(
        tool_call_id="code", tool_name="execute_code", content=content, details=details
    )

    prompt = prepare_prompt(
        [
            UserMessage(content="Draw a fox"),
            AssistantMessage(
                content=[ToolCall(id="code", name="execute_code", arguments={})]
            ),
            program,
            AssistantMessage(content=[TextContent(text="Here it is.")]),
            UserMessage(content="Make it blue"),
        ],
        system_prompt=None,
        custom_agent_prompt=None,
        reminder_message=None,
        context_files=None,
        token_counter=len,
    )
    [replayed] = [m for m in prompt if isinstance(m, ToolResultMessage)]
    assert replayed.text == content
