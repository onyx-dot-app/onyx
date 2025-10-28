from collections.abc import Callable
from typing import cast

import pytest
from litellm.litellm_core_utils.llm_response_utils.convert_dict_to_response import re
from pytest_mock import MockerFixture

from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import default_build_system_message
from onyx.chat.prompt_builder.answer_prompt_builder import (
    default_build_system_message_for_default_assistant_v2,
)
from onyx.llm.interfaces import LLMConfig
from onyx.llm.llm_provider_options import OPENAI_PROVIDER_NAME
from onyx.prompts.chat_prompts import DEFAULT_SYSTEM_PROMPT
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_implementations_v2.web import OPEN_URL_LONG_DESCRIPTION
from onyx.tools.tool_implementations_v2.web import WEB_SEARCH_LONG_DESCRIPTION
from tests.unit.onyx.chat.tools.utils import SimpleTestTool

SECTION_RE = r"(?ms)^\s*(#+)\s*{title}\s*\n(?P<body>.*?)(?:^\s*\1\s|\Z)"


def _section(content: str, title: str) -> str | None:
    m = re.search(SECTION_RE.format(title=re.escape(title)), content)
    return m.group("body") if m else None


def _assert_section(content: str, title: str, exists: bool) -> None:
    present = _section(content, title) is not None
    assert (
        present == exists
    ), f"Expected section '{title}' exists={exists}, got {present}.\nContent:\n{content}"


@pytest.fixture
def llm_config() -> LLMConfig:
    return LLMConfig(
        model_name="gpt-4o",
        model_provider=OPENAI_PROVIDER_NAME,
        temperature=0.0,
        max_input_tokens=10000,
    )


@pytest.fixture
def prompt_config() -> PromptConfig:
    return PromptConfig(
        system_prompt="You are helpful.",
        task_prompt="",
        datetime_aware=False,
    )


@pytest.fixture
def make_prompt_config() -> Callable:
    def _make_prompt_config(
        system_prompt: str, task_prompt: str, datetime_aware: bool
    ) -> PromptConfig:
        return PromptConfig(
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            datetime_aware=datetime_aware,
        )

    return _make_prompt_config


@pytest.fixture
def personalization() -> dict[str, str]:
    return {
        "name": "Jane Doe",
        "role": "Developer Advocate",
        "email": "jane@example.com",
    }


@pytest.fixture
def memories_callback(personalization: dict[str, str]) -> Callable[[], list[str]]:
    memories = ["Memory 1", "Memory 2"]

    def _inner() -> list[str]:
        return [
            f"User's name: {personalization['name']}",
            f"User's role: {personalization['role']}",
            f"User's email: {personalization['email']}",
            *memories,
        ]

    return _inner


@pytest.fixture
def test_tool() -> Tool:
    """A simple test tool fixture that implements the Tool interface."""
    return SimpleTestTool()


@pytest.fixture
def web_search_tool() -> Tool:
    """A web search tool fixture that implements the Tool interface."""
    return WebSearchTool(tool_id=2)


@pytest.fixture
def mocked_settings(mocker: MockerFixture) -> None:
    mocker.patch(
        "onyx.prompts.prompt_utils.load_settings",
        return_value=type(
            "Settings",
            (),
            {
                "company_name": "Acme Corp",
                "company_description": "Acme builds doors.",
            },
        )(),
    )


@pytest.mark.parametrize("has_memories", [True, False])
@pytest.mark.parametrize("has_company_settings", [True, False])
@pytest.mark.parametrize("datetime_aware", [True, False])
def test_system_message_includes_personalization(
    has_memories: bool,
    has_company_settings: bool,
    datetime_aware: bool,
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    memories_callback: Callable[[], list[str]],
    mocked_settings: None,
    mocker: MockerFixture,
) -> None:
    if not has_company_settings:
        mocker.patch(
            "onyx.prompts.prompt_utils.load_settings",
            side_effect=RuntimeError("missing"),
        )

    config = prompt_config
    if datetime_aware:
        config = prompt_config.model_copy(update={"datetime_aware": True})

    system_message = default_build_system_message(
        config,
        llm_config,
        memories_callback if has_memories else None,
    )

    assert system_message is not None
    content = cast(str, system_message.content)

    assert ("Acme builds doors." in content) == has_company_settings

    assert ("Acme Corp" in content) == has_company_settings

    assert ("Developer Advocate" in content) == has_memories
    assert ("Memory 1" in content) == has_memories

    datestring_pattern = (
        r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"\d{1,2},\s+\d{4}\b"
    )
    assert (re.search(datestring_pattern, content) is not None) == datetime_aware


@pytest.mark.parametrize("has_memories", [True, False])
@pytest.mark.parametrize("has_company_settings", [True, False])
@pytest.mark.parametrize(
    "datetime_aware", [True]
)  # default assistant is always datetime-aware
def test_system_message_includes_personalization_for_default_assistant(
    has_memories: bool,
    has_company_settings: bool,
    datetime_aware: bool,
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    memories_callback: Callable[[], list[str]],
    mocked_settings: None,
    mocker: MockerFixture,
) -> None:
    if not has_company_settings:
        mocker.patch(
            "onyx.prompts.prompt_utils.load_settings",
            side_effect=RuntimeError("missing"),
        )

    config = prompt_config
    if datetime_aware:
        config = prompt_config.model_copy(update={"datetime_aware": True})

    system_message = default_build_system_message_for_default_assistant_v2(
        config,
        llm_config,
        memories_callback if has_memories else None,
    )

    assert system_message is not None
    content = cast(str, system_message.content)

    assert ("Acme builds doors." in content) == has_company_settings

    assert ("Acme Corp" in content) == has_company_settings

    assert ("Developer Advocate" in content) == has_memories
    assert ("Memory 1" in content) == has_memories

    datestring_pattern = (
        r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"\d{1,2},\s+\d{4}\b"
    )
    assert (re.search(datestring_pattern, content) is not None) == datetime_aware


def test_tools_section_present_when_tools_given(
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    test_tool: Tool,
) -> None:
    tools = [test_tool]
    msg = default_build_system_message_for_default_assistant_v2(
        prompt_config, llm_config, memories_callback=None, tools=tools
    )
    content = cast(str, msg.content)

    _assert_section(content, "Tools", True)
    body = _section(content, "Tools")
    assert body is not None
    assert test_tool.name in body
    assert test_tool.description in body


def test_tools_section_empty_when_no_tools_given(
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
) -> None:
    msg = default_build_system_message_for_default_assistant_v2(
        prompt_config, llm_config, memories_callback=None, tools=[]
    )
    content = cast(str, msg.content)

    _assert_section(content, "Tools", False)


# TODO: Can remove the custom instruction ignore when equal to default
# after we do our cloud migration to set them all to empty where equal to default
def test_custom_instructions_gone_when_empty_or_default(
    make_prompt_config: Callable,
    llm_config: LLMConfig,
) -> None:
    msg = default_build_system_message_for_default_assistant_v2(
        make_prompt_config("", "", False), llm_config, memories_callback=None
    )
    content = cast(str, msg.content)
    _assert_section(content, "Custom Instructions", False)

    msg = default_build_system_message_for_default_assistant_v2(
        make_prompt_config(DEFAULT_SYSTEM_PROMPT, "", False),
        llm_config,
        memories_callback=None,
    )
    content = cast(str, msg.content)
    _assert_section(content, "Custom Instructions", False)


def test_custom_instructions_present_when_set(
    make_prompt_config: Callable,
    llm_config: LLMConfig,
) -> None:
    msg = default_build_system_message_for_default_assistant_v2(
        make_prompt_config("You are helpful.", "", False),
        llm_config,
        memories_callback=None,
    )
    content = cast(str, msg.content)
    _assert_section(content, "Custom Instructions", True)
    body = _section(content, "Custom Instructions")
    assert body is not None
    assert "You are helpful." in body


# TODO: Clean this up with a ToolV2 class that handles this instead of custom logic
# for the web search tool
def test_web_search_tool_present(
    prompt_config: PromptConfig,
    web_search_tool: Tool,
    llm_config: LLMConfig,
) -> None:
    msg = default_build_system_message_for_default_assistant_v2(
        prompt_config, llm_config, memories_callback=None, tools=[web_search_tool]
    )
    content = cast(str, msg.content)
    _assert_section(content, "Tools", True)
    body = _section(content, "Tools")
    assert body is not None
    assert "web_search" in body
    assert "open_url" in body
    assert WEB_SEARCH_LONG_DESCRIPTION in body
    assert OPEN_URL_LONG_DESCRIPTION in body
