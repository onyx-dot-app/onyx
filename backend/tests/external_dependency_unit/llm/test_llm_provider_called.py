from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.llm.constants import LlmProviderNames
from onyx.llm.override_models import LLMOverride
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.server.query_and_chat.chat_backend import create_new_chat_session
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import MessageResponseIDInfo
from tests.external_dependency_unit.answer.stream_test_assertions import (
    assert_answer_stream_part_correct,
)
from tests.external_dependency_unit.answer.stream_test_builder import StreamTestBuilder
from tests.external_dependency_unit.answer.stream_test_utils import submit_query
from tests.external_dependency_unit.answer.stream_test_utils import tokenise
from tests.external_dependency_unit.mock_llm import LLMAnswerResponse
from tests.external_dependency_unit.mock_llm import MockLLM


def _create_admin(db_session: Session) -> User:
    """Create a mock admin user for testing."""
    unique_email = f"admin_{uuid4().hex[:8]}@example.com"
    password_helper = PasswordHelper()
    password = password_helper.generate()
    hashed_password = password_helper.hash(password)

    user = User(
        id=uuid4(),
        email=unique_email,
        hashed_password=hashed_password,
        is_active=True,
        is_superuser=True,
        is_verified=True,
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_provider(
    db_session: Session,
    provider: LlmProviderNames,
    name: str,
    is_public: bool,
) -> int:
    result = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=name,
            provider=provider,
            api_key="sk-ant-api03-...",
            is_public=is_public,
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name="claude-3-5-sonnet-20240620",
                    is_visible=True,
                ),
            ],
        ),
        db_session=db_session,
    )
    return result.id


@contextmanager
def use_mock_llm() -> (
    Generator[tuple[MockLLM, dict[str, bool | str | None]], None, None]
):
    """Context manager that patches LLM factory functions and tracks which ones are called."""
    mock_llm = MockLLM()

    call_tracker: dict[str, bool | str | None] = {
        "get_default_llm_called": False,
        "get_llm_called": False,
        "provider": None,
    }

    def mock_get_default_llm(*_args: Any, **_kwargs: Any) -> MockLLM:
        call_tracker["get_default_llm_called"] = True
        return mock_llm

    def mock_get_llm(provider: str, *_args: Any, **_kwargs: Any) -> MockLLM:
        call_tracker["get_llm_called"] = True
        call_tracker["provider"] = provider
        return mock_llm

    with (
        patch(
            "onyx.llm.factory.get_default_llm",
            side_effect=mock_get_default_llm,
        ),
        patch(
            "onyx.llm.factory.get_llm",
            side_effect=mock_get_llm,
        ),
    ):
        yield mock_llm, call_tracker


def _cleanup_provider(db_session: Session, name: str) -> None:
    """Helper to clean up a test provider by name."""
    provider = fetch_existing_llm_provider(name=name, db_session=db_session)
    if provider:
        remove_llm_provider(db_session, provider.id)


def _assert_llm_calls(
    call_tracker: dict[str, bool | str | None], expected_provider: str
) -> None:
    """Assert that get_llm was called with expected provider and get_default_llm was not called."""
    assert not call_tracker[
        "get_default_llm_called"
    ], "get_default_llm should not be called when using private provider"
    assert call_tracker[
        "get_llm_called"
    ], "get_llm should be called when using private provider"
    assert (
        call_tracker["provider"] == expected_provider
    ), f"Expected provider '{expected_provider}', got '{call_tracker['provider']}'"


def _reset_call_tracker(call_tracker: dict[str, bool | str | None]) -> None:
    """Reset the call tracker for the next test iteration."""
    call_tracker["get_default_llm_called"] = False
    call_tracker["get_llm_called"] = False
    call_tracker["provider"] = None


def test_user_sends_message_to_private_provider(
    db_session: Session,
) -> None:
    """Test that messages sent to a private provider use get_llm instead of get_default_llm."""
    admin_user = _create_admin(db_session)

    # Create providers
    public_provider_id = _create_provider(
        db_session, LlmProviderNames.ANTHROPIC, "public-provider", True
    )
    _create_provider(db_session, LlmProviderNames.GOOGLE, "private-provider", False)

    update_default_provider(
        public_provider_id, "claude-3-5-sonnet-20240620", db_session
    )

    try:
        # Create chat session
        chat_session = create_new_chat_session(
            ChatSessionCreationRequest(),
            user=admin_user,
            db_session=db_session,
        )

        chat_session_id = chat_session.chat_session_id
        answer_tokens_1 = tokenise("Hello, how are you?")
        answer_tokens_2 = tokenise("I'm good, thank you!")

        with use_mock_llm() as (mock_llm, call_tracker):
            handler = StreamTestBuilder(llm_controller=mock_llm)

            # First message
            handler.add_response(LLMAnswerResponse(answer_tokens=answer_tokens_1))
            answer_stream = submit_query(
                query="Hello, how are you?",
                chat_session_id=chat_session_id,
                db_session=db_session,
                user=admin_user,
                llm_override=LLMOverride(
                    model_provider="private-provider",
                    model_version="claude-3-5-sonnet-20240620",
                ),
            )

            assert_answer_stream_part_correct(
                received=next(answer_stream),
                expected=MessageResponseIDInfo(
                    user_message_id=1,
                    reserved_assistant_message_id=1,
                ),
            )

            handler.expect_agent_response(
                answer_tokens=answer_tokens_1,
                turn_index=0,
            ).run_and_validate(stream=answer_stream)

            with pytest.raises(StopIteration):
                next(answer_stream)

            _assert_llm_calls(call_tracker, "google")
            _reset_call_tracker(call_tracker)

            # Second message
            handler.add_response(LLMAnswerResponse(answer_tokens=answer_tokens_2))
            answer_stream = submit_query(
                query="I'm good, thank you!",
                chat_session_id=chat_session_id,
                db_session=db_session,
                user=admin_user,
                llm_override=LLMOverride(
                    model_provider="private-provider",
                    model_version="claude-3-5-sonnet-20240620",
                ),
            )

            assert_answer_stream_part_correct(
                received=next(answer_stream),
                expected=MessageResponseIDInfo(
                    user_message_id=2,
                    reserved_assistant_message_id=2,
                ),
            )

            handler.expect_agent_response(
                answer_tokens=answer_tokens_2,
                turn_index=0,
            ).run_and_validate(stream=answer_stream)

            with pytest.raises(StopIteration):
                next(answer_stream)

            _assert_llm_calls(call_tracker, "google")

    finally:
        _cleanup_provider(db_session, "public-provider")
        _cleanup_provider(db_session, "private-provider")
