"""Stable tool rounds stay cacheable before changing file notices."""

import pytest

from onyx.chat.models import PersonaPromptConfig, PromptMetadata
from onyx.chat.prompt_formatting import prompt_metadata
from onyx.chat.prompt_utils import build_chat_prompt, prepare_prompt
from onyx.file_store.models import ExtractedContextFiles, FileToolMetadata
from onyx.llm.models import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.chat_prompts import REQUIRE_CITATION_GUIDANCE
from onyx.tools.tool_implementations.search.search_tool import SearchTool


@pytest.mark.parametrize("with_history", [False, True])
def test_stable_prefix_precedes_file_notices(with_history: bool) -> None:
    history: list[Message] = (
        [
            UserMessage(content="Find evidence"),
            AssistantMessage(content=[]),
            ToolResultMessage(
                tool_call_id="search", tool_name="search", content="Evidence"
            ),
        ]
        if with_history
        else []
    )
    original_history = [message.model_copy(deep=True) for message in history]
    task = UserMessage(content="Task instructions")
    reminder = UserMessage(
        content="Cite sources", metadata=PromptMetadata(is_reminder=True)
    )
    file = FileToolMetadata(
        file_id="large", filename="large.txt", approx_char_count=10000
    )
    forgotten = FileToolMetadata(
        file_id="old", filename="old.txt", approx_char_count=10000
    )
    prepared = prepare_prompt(
        history,
        system_prompt=SystemMessage(content="System instructions"),
        custom_agent_prompt=task,
        reminder_message=reminder,
        context_files=ExtractedContextFiles(
            file_texts=["Project contents"],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=2,
            file_metadata=[],
            uncapped_token_count=None,
            file_metadata_for_tool=[file],
        ),
        token_counter=len,
        all_injected_file_metadata={"old": forgotten},
        available_tool_names={"read_file"},
    )
    assert all(prompt_metadata(message).should_cache for message in prepared[:-3])
    assert all(not prompt_metadata(message).should_cache for message in prepared[-3:])
    assert "large.txt" in prepared[-3].text
    assert "old.txt" in prepared[-2].text
    assert prepared[-1] == reminder
    if with_history:
        assert prepared[-4].text == "Evidence"
    assert history == original_history
    assert not prompt_metadata(task).should_cache


@pytest.mark.parametrize("replace_system", [False, True])
@pytest.mark.parametrize("base_prompt", ["", "Base. {{CITATION_GUIDANCE}}"])
def test_citation_results_do_not_change_prompt_prefix(
    replace_system: bool, base_prompt: str, monkeypatch: pytest.MonkeyPatch
) -> None:

    monkeypatch.setattr("onyx.chat.prompt_utils.get_company_context", lambda: None)
    persona = PersonaPromptConfig(
        system_prompt="System. {{CITATION_GUIDANCE}}",
        task_prompt="Task. {{CITATION_GUIDANCE}}",
        datetime_aware=False,
        replace_base_system_prompt=replace_system,
    )
    files = ExtractedContextFiles(
        file_texts=[],
        image_files=[],
        use_as_search_filter=False,
        total_token_count=0,
        file_metadata=[],
        uncapped_token_count=None,
    )
    result = ToolResultMessage(
        tool_call_id="search", tool_name=SearchTool.NAME, content="Evidence"
    )
    prompts = [
        build_chat_prompt(
            tools=[],
            persona=persona,
            custom_prompt="Custom. {{CITATION_GUIDANCE}}",
            base_prompt=base_prompt,
            files=files,
            memory=None,
            inject_memories=False,
            reminders_enabled=True,
            results=results,
            previous_results=results,
            is_last_step=False,
        )
        for results in ([], [result])
    ]
    assert prompts[0].system_prompt == prompts[1].system_prompt
    assert prompts[0].custom_prompt == prompts[1].custom_prompt
    assert prompts[1].system_prompt is not None
    assert REQUIRE_CITATION_GUIDANCE.strip() not in prompts[1].system_prompt.text
    if prompts[1].custom_prompt is not None:
        assert REQUIRE_CITATION_GUIDANCE.strip() not in prompts[1].custom_prompt.text
    assert prompts[1].reminder is not None
    assert prompts[1].reminder.text.count(REQUIRE_CITATION_GUIDANCE.strip()) == 1


def test_followup_preserves_complete_prefix_with_project_text_and_images() -> None:
    from onyx.file_store.models import ChatFileType, ChatLoadedFile
    from onyx.llm.interfaces import LLMConfig
    from onyx.llm.models import ImageContentPart, TextContent

    image = ChatLoadedFile(
        file_id="project-image",
        filename="project.png",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        ),
        file_type=ChatFileType.IMAGE,
        content_text=None,
        token_count=100,
    )
    files = ExtractedContextFiles(
        file_texts=["Project evidence"],
        image_files=[image],
        use_as_search_filter=False,
        total_token_count=116,
        uncapped_token_count=116,
        file_metadata=[],
    )
    config = LLMConfig(
        model_provider="anthropic",
        model_name="claude-haiku-4-5",
        temperature=0,
        max_input_tokens=200_000,
        supports_images=True,
    )
    history: list[Message] = [
        UserMessage(content="First question"),
        AssistantMessage(content=[TextContent(text="Checking evidence")]),
        ToolResultMessage(
            tool_call_id="search", tool_name="search", content="Original evidence"
        ),
    ]

    def assemble(messages: list[Message], request_context: str) -> list[Message]:
        return prepare_prompt(
            messages,
            system_prompt=SystemMessage(content="System"),
            user_info_prompt=SystemMessage(content="User info"),
            custom_agent_prompt=UserMessage(content="Agent instructions"),
            context_files=files,
            request_context_message=UserMessage(
                content=request_context,
                cacheable=True,
                metadata=PromptMetadata(should_cache=True),
            ),
            reminder_message=None,
            token_counter=len,
            llm_config=config,
        )

    first = assemble(history, "First request context")
    followup = assemble(
        [
            *history,
            AssistantMessage(content=[TextContent(text="Answer")]),
            UserMessage(content="Follow-up question"),
        ],
        "Changed request context",
    )
    assert first[:-1] == followup[: len(first) - 1]
    assert all(message.cacheable for message in first[:-1])
    assert not first[-1].cacheable
    assert not followup[-1].cacheable
    assert first[-1].text == "First request context"
    project = first[3]
    assert isinstance(project, UserMessage) and isinstance(project.content, list)
    assert sum(isinstance(part, ImageContentPart) for part in project.content) == 1
    assert any(message.text == "Original evidence" for message in followup)
    assert prompt_metadata(history[0]).image_files is None
