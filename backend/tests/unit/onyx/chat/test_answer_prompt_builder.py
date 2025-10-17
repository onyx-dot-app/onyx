from collections.abc import Callable
from typing import cast

import pytest
from pytest_mock import MockerFixture

from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import default_build_system_message
from onyx.chat.prompt_builder.answer_prompt_builder import (
    default_build_system_message_v2,
)
from onyx.llm.interfaces import LLMConfig
from onyx.llm.llm_provider_options import OPENAI_PROVIDER_NAME


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


@pytest.mark.parametrize(
    "builder",
    [default_build_system_message, default_build_system_message_v2],
)
@pytest.mark.parametrize("has_memories", [True, False])
@pytest.mark.parametrize("has_company_settings", [True, False])
@pytest.mark.parametrize("datetime_aware", [True, False])
def test_system_message_includes_personalization(
    builder: Callable,
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

    system_message = builder(
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
    assert ("The current day and time" in content) == datetime_aware
