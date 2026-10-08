"""Stable tool rounds stay cacheable before changing file notices."""

import pytest

from onyx.chat.models import PersonaPromptConfig
from onyx.chat.prompt_formatting import PromptMetadata, prompt_metadata
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
    assert prepared[-1] is reminder
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
            ran_image_gen=False,
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


@pytest.mark.parametrize("replace_base", [False, True])
@pytest.mark.parametrize("base_prompt", ["Base prompt", ""])
def test_project_instructions_supplement_agent_prompt(
    replace_base: bool, base_prompt: str
) -> None:
    from unittest.mock import Mock

    from onyx.chat.prepare import get_custom_agent_prompt

    persona = PersonaPromptConfig(
        system_prompt="Answer tersely.",
        task_prompt=None,
        replace_base_system_prompt=replace_base,
        datetime_aware=False,
    )
    custom = get_custom_agent_prompt(
        Mock(
            id=1,
            system_prompt=persona.system_prompt,
            replace_base_system_prompt=replace_base,
        ),
        Mock(project=Mock(instructions="Use the project glossary.")),
    )
    files = ExtractedContextFiles(
        file_texts=[],
        image_files=[],
        use_as_search_filter=False,
        total_token_count=0,
        file_metadata=[],
        uncapped_token_count=None,
    )
    prompt = build_chat_prompt(
        tools=[],
        persona=persona,
        custom_prompt=custom,
        base_prompt=base_prompt,
        files=files,
        memory=None,
        inject_memories=False,
        reminders_enabled=False,
        results=[],
        previous_results=[],
        is_last_step=False,
        ran_image_gen=False,
    )
    history = prepare_prompt(
        [UserMessage(content="Question")],
        system_prompt=prompt.system_prompt,
        custom_agent_prompt=prompt.custom_prompt,
        reminder_message=None,
        context_files=files,
        token_counter=len,
    )
    text = "\n".join(message.text for message in history)
    assert text.count("Answer tersely.") == 1
    assert text.count("Use the project glossary.") == 1
    assert history[-1].text == "Question"
    if replace_base:
        assert isinstance(history[0], SystemMessage)
        assert history[0].text == "Answer tersely."
        assert isinstance(history[1], UserMessage)
        assert history[1].text == "Use the project glossary."
        assert "Base prompt" not in text
    elif base_prompt:
        assert isinstance(history[1], UserMessage)
    else:
        assert isinstance(history[0], SystemMessage)
