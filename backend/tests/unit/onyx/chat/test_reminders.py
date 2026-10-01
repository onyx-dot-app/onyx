from onyx.chat.models import ChatReminderContext
from onyx.chat.prompt_utils import build_chat_reminder
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.llm.models import ToolResultMessage
from onyx.prompts.chat_prompts import IMAGE_GEN_REMINDER, OPEN_URL_REMINDER
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool


def test_search_reminder_can_be_removed_without_changing_tool_results() -> None:
    response = ToolResultMessage(
        content="Search results", tool_name=SearchTool.NAME, tool_call_id="search"
    )
    original = response.model_copy(deep=True)
    context = ChatReminderContext(
        ran_image_gen=False,
        has_open_url_tool=False,
        out_of_cycles=False,
        persona_task_prompt="User instructions",
        has_context_documents=False,
    )
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
    context = ChatReminderContext(
        ran_image_gen=False,
        has_open_url_tool=True,
        out_of_cycles=False,
        persona_task_prompt=None,
        has_context_documents=False,
    )
    assert build_chat_reminder(context, [], [result], enabled=True) == OPEN_URL_REMINDER
    context.has_open_url_tool = False
    assert build_chat_reminder(context, [], [result], enabled=True) is None
    context.has_open_url_tool = True
    context.out_of_cycles = True
    assert build_chat_reminder(context, [], [result], enabled=True) != OPEN_URL_REMINDER
    context.out_of_cycles = False
    context.ran_image_gen = True
    assert (
        build_chat_reminder(context, [], [result], enabled=True) == IMAGE_GEN_REMINDER
    )
