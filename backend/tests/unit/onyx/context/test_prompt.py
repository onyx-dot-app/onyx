"""Prompt assembly preserves history and makes retained file references usable."""

import pytest

from onyx.agents.compaction import checkpoint_matches, history_digest, working_messages
from onyx.agents.transcript import CompactionCheckpoint
from onyx.context.messages import PromptMetadata, prompt_metadata
from onyx.context.prompt import prepare_prompt
from onyx.file_store.models import (
    ChatFileType,
    ChatLoadedFile,
    ContextFileMetadata,
    ExtractedContextFiles,
    FileToolMetadata,
)
from onyx.llm.models import (
    AssistantMessage,
    Message,
    SystemMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.chat_prompts import TOOL_CALL_RESPONSE_CROSS_MESSAGE


def test_instructions_files_and_reminder_surround_current_task() -> None:
    history: list[Message] = [
        UserMessage(content="Earlier question"),
        AssistantMessage(content=[TextContent(text="Earlier answer")]),
        UserMessage(content="Current question"),
        AssistantMessage(content=[ToolCall(id="search", name="search", arguments={})]),
        ToolResultMessage(
            tool_call_id="search", tool_name="search", content="Evidence"
        ),
    ]
    original = [message.model_dump() for message in history]
    context = ExtractedContextFiles(
        file_texts=["Project evidence"],
        image_files=[],
        use_as_search_filter=False,
        total_token_count=16,
        uncapped_token_count=16,
        file_metadata=[
            ContextFileMetadata(
                file_id="project",
                filename="project.txt",
                file_content="Project evidence",
            )
        ],
        file_metadata_for_tool=[
            FileToolMetadata(
                file_id="large", filename="large.txt", approx_char_count=100000
            )
        ],
    )
    result = prepare_prompt(
        system_prompt=SystemMessage(content="System instructions"),
        custom_agent_prompt=UserMessage(content="Task instructions"),
        messages=history,
        reminder_message=UserMessage(
            content="Cite sources", metadata=PromptMetadata(is_reminder=True)
        ),
        context_files=context,
        token_counter=len,
    )
    assert [message.text for message in result[:4]] == [
        "System instructions",
        "Earlier question",
        "Earlier answer",
        "Task instructions",
    ]
    assert '"title": "project.txt"' in result[4].text
    assert '"contents": "Project evidence"' in result[4].text
    assert 'file_id="large"' in result[5].text
    assert [message.text for message in result[6:]] == [
        "Current question",
        "",
        "Evidence",
        "Cite sources",
    ]
    assert isinstance(result[7], AssistantMessage)
    assert result[7].tool_calls[0].id == "search"
    assert [message.model_dump() for message in history] == original
    assert prompt_metadata(result[0]).should_cache


def test_project_image_already_in_history_is_not_duplicated() -> None:
    image = ChatLoadedFile(
        file_id="image",
        filename="image.png",
        content=b"image",
        file_type=ChatFileType.IMAGE,
        content_text=None,
        token_count=100,
    )
    history: list[Message] = [
        UserMessage(
            content="Describe the image",
            metadata=PromptMetadata(image_files=[image], image_token_count=100),
        )
    ]
    result = prepare_prompt(
        system_prompt=None,
        custom_agent_prompt=None,
        messages=history,
        reminder_message=None,
        context_files=ExtractedContextFiles(
            file_texts=[],
            image_files=[image],
            use_as_search_filter=False,
            total_token_count=100,
            uncapped_token_count=100,
            file_metadata=[],
        ),
        token_counter=len,
    )
    images = [
        image
        for message in result
        for image in (prompt_metadata(message).image_files or [])
    ]
    assert [image.file_id for image in images] == ["image"]


@pytest.mark.parametrize("keep_first_file", [True, False])
def test_file_reader_metadata_covers_only_missing_file_contents(
    keep_first_file: bool,
) -> None:
    first = FileToolMetadata(
        file_id="first", filename="first.txt", approx_char_count=100
    )
    second = FileToolMetadata(
        file_id="second", filename="second.txt", approx_char_count=200
    )
    history: list[Message] = []
    if keep_first_file:
        history.append(
            UserMessage(
                content="First file contents", metadata=PromptMetadata(file_id="first")
            )
        )
    history.append(UserMessage(content="Compare the files"))
    result = prepare_prompt(
        system_prompt=None,
        custom_agent_prompt=None,
        messages=history,
        reminder_message=None,
        context_files=None,
        token_counter=len,
        all_injected_file_metadata={"first": first, "second": second},
    )
    metadata = next(message.text for message in result if "read_file" in message.text)
    assert 'file_id="second"' in metadata
    assert ('file_id="first"' in metadata) is not keep_first_file
    assert result[-1].text == "Compare the files"


@pytest.mark.parametrize(
    "history", [[], [AssistantMessage(content=[TextContent(text="Summary")])]]
)
def test_prompt_can_be_rebuilt_without_a_user_message(history: list[Message]) -> None:
    result = prepare_prompt(
        system_prompt=SystemMessage(content="System"),
        custom_agent_prompt=UserMessage(content="Task"),
        messages=history,
        reminder_message=None,
        context_files=None,
        token_counter=len,
    )
    assert [message.text for message in result] == [
        "System",
        *[message.text for message in history],
        "Task",
    ]


def test_historical_tool_filter_preserves_checkpoint_and_current_evidence() -> None:
    prior_result = ToolResultMessage(
        tool_call_id="old",
        tool_name="web_search",
        content="Old evidence",
        metadata=PromptMetadata(omit_tool_result_content=True),
    )
    image_result = ToolResultMessage(
        tool_call_id="image",
        tool_name="generate_image",
        content='[{"file_id":"image"}]',
    )
    current_result = ToolResultMessage(
        tool_call_id="new",
        tool_name="web_search",
        content="Current evidence",
    )
    history: list[Message] = [
        UserMessage(content="First question"),
        AssistantMessage(content=[TextContent(text="First answer")]),
        prior_result,
        image_result,
        UserMessage(content="Next question"),
        current_result,
    ]
    checkpoint = CompactionCheckpoint(
        summary="First exchange",
        covered_count=2,
        covered_digest=history_digest(history[:2]),
    )
    original_digest = history_digest(history)
    request = prepare_prompt(
        working_messages(history, checkpoint),
        system_prompt=None,
        custom_agent_prompt=None,
        reminder_message=None,
        context_files=None,
        token_counter=len,
    )
    results = [message for message in request if isinstance(message, ToolResultMessage)]
    assert [message.text for message in results] == [
        TOOL_CALL_RESPONSE_CROSS_MESSAGE,
        image_result.text,
        "Current evidence",
    ]
    assert prompt_metadata(results[0]).token_count == len(
        TOOL_CALL_RESPONSE_CROSS_MESSAGE
    )
    assert prior_result.text == "Old evidence"
    assert history_digest(history) == original_digest
    assert checkpoint_matches(history, checkpoint)
