"""Tests for PromptConfig.from_model() behavior with default and custom personas."""

from typing import cast

import pytest
from sqlalchemy.orm import Session

from onyx.chat.models import PromptConfig
from onyx.db.models import Persona
from onyx.llm.override_models import PromptOverride


@pytest.fixture
def default_persona() -> Persona:
    """Create a persona marked as the default assistant."""
    persona = Persona(
        id=1,
        name="Default Assistant",
        description="Default assistant",
        system_prompt="You are a helpful, thoughtful assistant.",
        task_prompt="Answer questions thoroughly.",
        datetime_aware=True,
        is_default_persona=True,
        deleted=False,
        is_visible=True,
        is_public=True,
        builtin_persona=True,
        llm_relevance_filter=False,
        llm_filter_extraction=False,
        recency_bias="base_decay",
        num_chunks=10.0,
        chunks_above=0,
        chunks_below=0,
    )
    return persona


@pytest.fixture
def custom_persona() -> Persona:
    """Create a custom (non-default) persona."""
    persona = Persona(
        id=2,
        name="Code Expert",
        description="An expert in programming",
        system_prompt="You are an expert programmer who explains code clearly.",
        task_prompt="Help with coding questions.",
        datetime_aware=False,
        is_default_persona=False,
        deleted=False,
        is_visible=True,
        is_public=True,
        builtin_persona=False,
        llm_relevance_filter=False,
        llm_filter_extraction=False,
        recency_bias="base_decay",
        num_chunks=10.0,
        chunks_above=0,
        chunks_below=0,
    )
    return persona


@pytest.fixture
def mock_db_session(
    default_persona: Persona, monkeypatch: pytest.MonkeyPatch
) -> Session:
    """Create a mock database session that returns the default persona."""
    from onyx.db import persona as persona_module

    def mock_get_default_persona(db_session: Session) -> Persona:
        return default_persona

    monkeypatch.setattr(
        persona_module,
        "get_default_persona",
        mock_get_default_persona,
    )

    # Return a mock Session object (empty dict works for our purposes)
    return {}  # type: ignore


def test_prompt_config_from_default_persona(
    default_persona: Persona,
    mock_db_session: Session,
) -> None:
    """Test PromptConfig.from_model() when persona IS the default assistant."""
    prompt_config = PromptConfig.from_model(default_persona, db_session=mock_db_session)

    # When persona is default, its system_prompt should be the default_behavior_system_prompt
    assert prompt_config.default_behavior_system_prompt == default_persona.system_prompt

    # custom_instruction should be None for the default persona
    assert prompt_config.custom_instructions is None

    # reminder and datetime_aware should be preserved
    assert prompt_config.reminder == default_persona.task_prompt
    assert prompt_config.datetime_aware == default_persona.datetime_aware


def test_prompt_config_from_custom_persona(
    default_persona: Persona,
    custom_persona: Persona,
    mock_db_session: Session,
) -> None:
    """Test PromptConfig.from_model() when persona is NOT the default assistant."""
    prompt_config = PromptConfig.from_model(custom_persona, db_session=mock_db_session)

    # default_behavior_system_prompt should come from the default persona
    assert prompt_config.default_behavior_system_prompt == default_persona.system_prompt

    # custom_instruction should be the custom persona's system_prompt
    assert prompt_config.custom_instructions == custom_persona.system_prompt

    # reminder and datetime_aware should be from the custom persona
    assert prompt_config.reminder == custom_persona.task_prompt
    assert prompt_config.datetime_aware == custom_persona.datetime_aware


def test_prompt_config_with_no_default_persona(
    custom_persona: Persona,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test PromptConfig.from_model() when no default persona exists."""
    from onyx.db import persona as persona_module

    def mock_get_default_persona_none(db_session: Session) -> None:
        return None

    monkeypatch.setattr(
        persona_module,
        "get_default_persona",
        mock_get_default_persona_none,
    )

    mock_db_session = cast(Session, {})
    prompt_config = PromptConfig.from_model(custom_persona, db_session=mock_db_session)

    # default_behavior_system_prompt should be empty string when no default exists
    assert prompt_config.default_behavior_system_prompt == ""

    # custom_instruction should still be the custom persona's system_prompt
    assert prompt_config.custom_instructions == custom_persona.system_prompt


def test_prompt_config_with_prompt_override_on_default_persona(
    default_persona: Persona,
    mock_db_session: Session,
) -> None:
    """Test PromptConfig.from_model() with prompt override on default persona."""
    override = PromptOverride(
        system_prompt="Override system prompt",
        task_prompt="Override task prompt",
    )

    prompt_config = PromptConfig.from_model(
        default_persona,
        db_session=mock_db_session,
        prompt_override=override,
    )

    # Override should apply to default_behavior_system_prompt for default persona
    assert prompt_config.default_behavior_system_prompt == override.system_prompt

    # custom_instruction should still be None
    assert prompt_config.custom_instructions is None

    # reminder should use the override
    assert prompt_config.reminder == override.task_prompt


def test_prompt_config_with_prompt_override_on_custom_persona(
    default_persona: Persona,
    custom_persona: Persona,
    mock_db_session: Session,
) -> None:
    """Test PromptConfig.from_model() with prompt override on custom persona."""
    override = PromptOverride(
        system_prompt="Override system prompt",
        task_prompt="Override task prompt",
    )

    prompt_config = PromptConfig.from_model(
        custom_persona,
        db_session=mock_db_session,
        prompt_override=override,
    )

    # default_behavior_system_prompt should still come from default persona
    assert prompt_config.default_behavior_system_prompt == default_persona.system_prompt

    # Override should apply to custom_instruction for non-default persona
    assert prompt_config.custom_instructions == override.system_prompt

    # reminder should use the override
    assert prompt_config.reminder == override.task_prompt


def test_prompt_config_preserves_datetime_aware(
    custom_persona: Persona,
    mock_db_session: Session,
) -> None:
    """Test that datetime_aware is correctly preserved from the persona."""
    # Custom persona has datetime_aware=False
    prompt_config = PromptConfig.from_model(custom_persona, db_session=mock_db_session)

    assert prompt_config.datetime_aware is False


def test_prompt_config_with_empty_system_prompts(
    mock_db_session: Session,
) -> None:
    """Test PromptConfig.from_model() when persona has empty system_prompt."""
    persona = Persona(
        id=3,
        name="Empty Prompt Persona",
        description="Test persona",
        system_prompt="",
        task_prompt="",
        datetime_aware=True,
        is_default_persona=False,
        deleted=False,
        is_visible=True,
        is_public=True,
        builtin_persona=False,
        llm_relevance_filter=False,
        llm_filter_extraction=False,
        recency_bias="base_decay",
        num_chunks=10.0,
        chunks_above=0,
        chunks_below=0,
    )

    prompt_config = PromptConfig.from_model(persona, db_session=mock_db_session)

    # custom_instruction should be None when system_prompt is empty
    assert prompt_config.custom_instructions is None

    # reminder should be empty string
    assert prompt_config.reminder == ""
