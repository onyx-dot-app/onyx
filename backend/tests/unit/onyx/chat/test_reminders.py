import pytest

from onyx.chat.models import ChatReminderContext
from onyx.chat.prompt_utils import build_chat_reminder
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.llm.models import ToolResultMessage
from onyx.prompts.chat_prompts import (
    ANSWER_COMPLETENESS_REMINDER,
    ANSWER_COVERAGE_GUIDANCE,
    IMAGE_GEN_REMINDER,
    LAST_CYCLE_CITATION_REMINDER,
    OPEN_URL_REMINDER,
    REQUIRE_CITATION_GUIDANCE,
)
from onyx.tools.models import GeneratedImage
from onyx.tools.tool_implementations.code_mode.code_mode_tool import CodeModeTool
from onyx.tools.tool_implementations.code_mode.models import (
    CodeModeCall,
    CodeModeExecutionResult,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool

IMAGES = FinalImageGenerationResponse(
    generated_images=[
        GeneratedImage(file_id="image-1", url="/api/file/image-1", revised_prompt="a")
    ]
)


def _context(
    *,
    task_prompt: str | None = None,
    open_url: bool = False,
    context_documents: bool = False,
    out_of_cycles: bool = False,
) -> ChatReminderContext:
    return ChatReminderContext(
        has_open_url_tool=open_url,
        out_of_cycles=out_of_cycles,
        persona_task_prompt=task_prompt,
        has_context_documents=context_documents,
    )


def _direct_image() -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id="image",
        tool_name=ImageGenerationTool.NAME,
        content="[]",
        details=IMAGES,
    )


def _nested_image() -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id="code",
        tool_name=CodeModeTool.NAME,
        content="Execution completed",
        details=CodeModeExecutionResult(
            cell_id=1,
            code="await generate_image(prompt='a')",
            status="completed",
            calls=[
                CodeModeCall(
                    id="code:0",
                    state="ok",
                    index=0,
                    tool_name=ImageGenerationTool.NAME,
                    function_name=ImageGenerationTool.NAME,
                    arguments={"prompt": "a"},
                    details=IMAGES,
                )
            ],
        ),
    )


def test_search_reminder_can_be_removed_without_changing_tool_results() -> None:
    response = ToolResultMessage(
        content="Search results", tool_name=SearchTool.NAME, tool_call_id="search"
    )
    original = response.model_copy(deep=True)
    context = _context(task_prompt="User instructions")
    enabled = build_chat_reminder(context, [response], [response], enabled=True)
    disabled = build_chat_reminder(context, [response], [response], enabled=False)
    assert enabled != disabled
    assert disabled == "User instructions"
    assert response == original


def test_web_search_reminder_requires_available_open_url_tool() -> None:
    document = SearchDoc(
        document_id="web-result",
        chunk_ind=0,
        semantic_identifier="Result",
        link="https://example.com",
        blurb="Evidence",
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    result = ToolResultMessage(
        tool_call_id="search",
        tool_name=WebSearchTool.NAME,
        content="Evidence",
        details=SearchDocsResponse(
            search_docs=[document], citation_mapping={1: "web-result"}
        ),
    )
    context = _context(open_url=True)
    assert build_chat_reminder(context, [], [result], enabled=True) == OPEN_URL_REMINDER
    cited = build_chat_reminder(context, [result], [result], enabled=True)
    assert cited is not None
    assert OPEN_URL_REMINDER in cited
    assert REQUIRE_CITATION_GUIDANCE.strip() in cited
    context.has_open_url_tool = False
    assert build_chat_reminder(context, [], [result], enabled=True) is None
    context.has_open_url_tool = True
    context.out_of_cycles = True
    assert (
        build_chat_reminder(context, [], [result], enabled=True)
        == LAST_CYCLE_CITATION_REMINDER
    )


@pytest.mark.parametrize("result", [_direct_image(), _nested_image()])
def test_generated_images_add_a_reminder_after_the_task_prompt(
    result: ToolResultMessage,
) -> None:
    context = _context(task_prompt="Answer in French.")
    reminder = build_chat_reminder(context, [result], [result], enabled=True)
    assert reminder == f"Answer in French.\n\n{IMAGE_GEN_REMINDER}"
    assert build_chat_reminder(context, [], [], enabled=True) == "Answer in French."


def test_image_without_generated_files_adds_no_reminder() -> None:
    failed = ToolResultMessage(
        tool_call_id="image",
        tool_name=ImageGenerationTool.NAME,
        content="failed",
        details=FinalImageGenerationResponse(generated_images=[]),
        is_error=True,
    )
    assert build_chat_reminder(_context(), [failed], [failed], enabled=True) is None


@pytest.mark.parametrize("image_generated", [False, True])
@pytest.mark.parametrize("authored_guidance", [False, True])
def test_reminder_retains_citation_guidance(
    image_generated: bool, authored_guidance: bool
) -> None:
    context = _context(
        task_prompt=REQUIRE_CITATION_GUIDANCE if authored_guidance else "Task",
        context_documents=True,
    )
    results = [_direct_image()] if image_generated else []
    reminder = build_chat_reminder(context, results, results, enabled=True)
    assert reminder is not None
    assert reminder.count(REQUIRE_CITATION_GUIDANCE.strip()) == 1
    assert ANSWER_COVERAGE_GUIDANCE.strip() in reminder
    assert ANSWER_COMPLETENESS_REMINDER in reminder
    assert (IMAGE_GEN_REMINDER in reminder) == image_generated


@pytest.mark.parametrize("image_succeeds", [True, False])
@pytest.mark.parametrize("nested", [True, False])
def test_image_and_web_search_keep_the_task_instructions(
    image_succeeds: bool, nested: bool
) -> None:
    image = _direct_image()
    if not image_succeeds:
        image = image.model_copy(
            update={
                "details": FinalImageGenerationResponse(generated_images=[]),
                "is_error": True,
            }
        )
    if nested:
        nested_result = _nested_image()
        assert isinstance(nested_result.details, CodeModeExecutionResult)
        nested_result.details.calls[0] = nested_result.details.calls[0].model_copy(
            update={
                "details": image.details,
                "state": "ok" if image_succeeds else "error",
            }
        )
        image = nested_result
    document = SearchDoc(
        document_id="web-result",
        chunk_ind=0,
        semantic_identifier="Result",
        link="https://example.com",
        blurb="Evidence",
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    search = ToolResultMessage(
        tool_call_id="search",
        tool_name=WebSearchTool.NAME,
        content="Evidence",
        details=SearchDocsResponse(
            search_docs=[document], citation_mapping={1: "web-result"}
        ),
    )
    context = _context(task_prompt="Answer in French.", open_url=True)
    reminder = build_chat_reminder(
        context, [image, search], [image, search], enabled=True
    )
    assert reminder is not None
    assert reminder.startswith("Answer in French.")
    assert (IMAGE_GEN_REMINDER in reminder) == image_succeeds
    assert REQUIRE_CITATION_GUIDANCE.strip() in reminder
