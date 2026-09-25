from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from onyx.db.enums import AccountType
from onyx.db.llm import (
    fetch_existing_llm_provider,
    remove_llm_provider,
    update_default_provider,
    upsert_llm_provider,
)
from onyx.db.models import User
from onyx.db.users import assign_user_to_default_groups__no_commit
from onyx.llm.constants import LlmProviderNames
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.override_models import LLMOverride
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from onyx.server.query_and_chat.chat_backend import create_new_chat_session
from onyx.server.query_and_chat.models import (
    ChatSessionCreationRequest,
)
from tests.external_dependency_unit.answer.stream_test_utils import (
    final_answer,
    submit_query,
)
from tests.external_dependency_unit.mock_llm import LLMAnswerResponse, MockLLM


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
        account_type=AccountType.STANDARD,
    )
    db_session.add(user)
    db_session.flush()
    assign_user_to_default_groups__no_commit(db_session, user, is_admin=True)
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
def use_mock_llm() -> Generator[
    tuple[MockLLM, dict[str, bool | str | None]], None, None
]:
    """Context manager that patches LLM factory functions and tracks which ones are called."""
    mock_llm = MockLLM()

    call_tracker: dict[str, bool | str | None] = {
        "get_default_llm_called": False,
        "get_llm_called": False,
        "provider": None,
    }

    def mock_get_default_llm(*_args: Any, **_kwargs: Any) -> LitellmLLM:
        call_tracker["get_default_llm_called"] = True
        return mock_llm

    def mock_get_llm(provider: str, *_args: Any, **_kwargs: Any) -> LitellmLLM:
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
    assert not call_tracker["get_default_llm_called"], (
        "get_default_llm should not be called when using private provider"
    )
    assert call_tracker["get_llm_called"], (
        "get_llm should be called when using private provider"
    )
    assert call_tracker["provider"] == expected_provider, (
        f"Expected provider '{expected_provider}', got '{call_tracker['provider']}'"
    )


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
        with use_mock_llm() as (mock_llm, call_tracker):
            for answer in ["Hello, how are you?", "I am good, thank you!"]:
                mock_llm.add_response(LLMAnswerResponse(answer_tokens=[answer]))
                mock_llm.forward_till_end()
                parts = list(
                    submit_query(
                        query=answer,
                        chat_session_id=chat_session_id,
                        user=admin_user,
                        llm_override=LLMOverride(
                            model_provider="private-provider",
                            model_version="claude-3-5-sonnet-20240620",
                        ),
                    )
                )
                assert final_answer(parts) == answer
                _assert_llm_calls(call_tracker, "google")
                _reset_call_tracker(call_tracker)

    finally:
        _cleanup_provider(db_session, "public-provider")
        _cleanup_provider(db_session, "private-provider")
