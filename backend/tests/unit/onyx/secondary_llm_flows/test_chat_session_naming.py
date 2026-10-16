from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import Request

from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.db.enums import LLMModelFlowType
from onyx.db.models import ChatMessage, LLMProvider, ModelConfiguration
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.secondary_llm_flows.chat_session_naming import (
    DEFAULT_CHAT_SESSION_NAME,
    get_fallback_chat_session_name,
)
from onyx.server.query_and_chat.chat_backend import (
    _generate_or_fallback_chat_session_name,
)


def _chat_message(message: str, message_type: MessageType) -> ChatMessage:
    return ChatMessage(
        message=message, message_type=message_type, token_count=len(message)
    )


@pytest.fixture
def utility_model() -> ModelConfiguration:
    model = ModelConfiguration(
        id=1,
        name="utility-model",
        is_visible=False,
        max_input_tokens=4096,
        is_router=False,
    )
    LLMProvider(
        id=1,
        name="utility-provider",
        provider="openai",
        api_key="utility-key",
        is_public=True,
        is_auto_mode=False,
        model_configurations=[model],
    )
    return model


@pytest.fixture
def naming_llm() -> MagicMock:
    llm = MagicMock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="utility-model",
        temperature=0,
        max_input_tokens=4096,
        api_key="utility-key",
    )
    return llm


def test_fallback_chat_session_name_uses_first_user_message() -> None:
    chat_history = [
        _chat_message("Assistant text", MessageType.ASSISTANT),
        _chat_message("A" * 50, MessageType.USER),
        _chat_message("Later user text", MessageType.USER),
    ]

    assert get_fallback_chat_session_name(chat_history) == f"{'A' * 40}..."


def test_fallback_chat_session_name_handles_empty_history() -> None:
    assert get_fallback_chat_session_name([]) == DEFAULT_CHAT_SESSION_NAME


def test_rate_limited_chat_naming_returns_fallback() -> None:
    first_user_message = "Explain cost-based usage metering"
    chat_history = [_chat_message(first_user_message, MessageType.USER)]
    request = MagicMock()
    user = MagicMock()
    user.id = uuid4()

    with (
        patch(
            "onyx.server.query_and_chat.chat_backend.check_token_rate_limits",
            side_effect=OnyxError(OnyxErrorCode.RATE_LIMITED),
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_llm_for_persona"
        ) as get_llm_for_persona,
    ):
        generated_name = _generate_or_fallback_chat_session_name(
            chat_history=chat_history,
            request=request,
            user=user,
            chat_session_id=uuid4(),
            persona=None,
            llm_override=None,
        )

    assert generated_name == first_user_message
    get_llm_for_persona.assert_not_called()


def test_configured_naming_model_names_chat_without_session_model(
    utility_model: ModelConfiguration,
    naming_llm: MagicMock,
) -> None:
    first_message = _chat_message("Explain usage metering", MessageType.USER)
    first_message.token_count = 2000
    latest_message = _chat_message("Charge for tokens used", MessageType.ASSISTANT)
    latest_message.token_count = 2000
    oversized_message = _chat_message("A" * 3001, MessageType.USER)
    request = Request(
        {"type": "http", "headers": [(b"x-request-id", b"naming-request")]}
    )

    def fetch_default(
        _session: object, flow: LLMModelFlowType
    ) -> ModelConfiguration | None:
        return utility_model if flow == LLMModelFlowType.CHAT_NAMING else None

    with (
        patch("onyx.server.query_and_chat.chat_backend.check_token_rate_limits"),
        patch(
            "onyx.server.query_and_chat.chat_backend.LITELLM_PASS_THROUGH_HEADERS",
            ["x-request-id"],
        ),
        patch("onyx.llm.factory.get_session_with_current_tenant") as session_factory,
        patch("onyx.llm.factory.fetch_default_model", side_effect=fetch_default),
        patch(
            "onyx.llm.factory.llm_from_provider", return_value=naming_llm
        ) as build_utility,
        patch("onyx.llm.factory.check_llm_cost_limit_for_provider") as utility_cost,
        patch("onyx.llm.factory.get_current_tenant_id", return_value="naming-tenant"),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_llm_for_persona",
            side_effect=ValueError("Session model is unavailable"),
        ) as session_llm,
        patch(
            "onyx.server.query_and_chat.chat_backend.check_llm_cost_limit_for_provider"
        ) as session_cost,
        patch(
            "onyx.server.query_and_chat.chat_backend.get_llm_token_counter",
            return_value=len,
        ),
        patch("onyx.server.query_and_chat.chat_backend.ensure_trace"),
        patch(
            "onyx.server.query_and_chat.chat_backend.generate_chat_session_name",
            return_value="Usage metering",
        ) as generate,
    ):
        title = _generate_or_fallback_chat_session_name(
            chat_history=[first_message, latest_message, oversized_message],
            request=request,
            user=MagicMock(),
            chat_session_id=uuid4(),
            persona=None,
            llm_override=None,
        )

    assert title == "Usage metering"
    session_llm.assert_not_called()
    session_cost.assert_not_called()
    utility_cost.assert_called_once_with(
        db_session=session_factory.return_value.__enter__.return_value,
        tenant_id="naming-tenant",
        llm_provider_api_key="utility-key",
    )
    assert build_utility.call_args.kwargs["additional_headers"] == {
        "x-request-id": "naming-request"
    }
    generate.assert_called_once_with(
        chat_history=[
            ChatMessageSimple(
                message="Charge for tokens used",
                message_type=MessageType.ASSISTANT,
                token_count=2000,
                image_files=None,
            )
        ],
        llm=naming_llm,
    )


def test_unset_utilities_check_session_provider_cost_once(
    naming_llm: MagicMock,
) -> None:
    naming_llm.config = naming_llm.config.model_copy(update={"api_key": "session-key"})
    user = MagicMock()
    persona = MagicMock()
    override = MagicMock()
    request = Request(
        {"type": "http", "headers": [(b"x-request-id", b"naming-request")]}
    )

    with (
        patch("onyx.server.query_and_chat.chat_backend.check_token_rate_limits"),
        patch(
            "onyx.server.query_and_chat.chat_backend.LITELLM_PASS_THROUGH_HEADERS",
            ["x-request-id"],
        ),
        patch("onyx.llm.factory.get_session_with_current_tenant"),
        patch("onyx.llm.factory.fetch_default_model", return_value=None),
        patch("onyx.llm.factory.check_llm_cost_limit_for_provider") as utility_cost,
        patch(
            "onyx.server.query_and_chat.chat_backend.get_llm_for_persona",
            return_value=naming_llm,
        ) as session_llm,
        patch(
            "onyx.server.query_and_chat.chat_backend.get_session_with_current_tenant"
        ) as session_factory,
        patch(
            "onyx.server.query_and_chat.chat_backend.get_current_tenant_id",
            return_value="naming-tenant",
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.check_llm_cost_limit_for_provider"
        ) as session_cost,
        patch(
            "onyx.server.query_and_chat.chat_backend.get_llm_token_counter",
            return_value=len,
        ),
        patch("onyx.server.query_and_chat.chat_backend.ensure_trace"),
        patch(
            "onyx.server.query_and_chat.chat_backend.generate_chat_session_name",
            return_value="Session title",
        ),
    ):
        title = _generate_or_fallback_chat_session_name(
            chat_history=[_chat_message("Explain usage metering", MessageType.USER)],
            request=request,
            user=user,
            chat_session_id=uuid4(),
            persona=persona,
            llm_override=override,
        )

    assert title == "Session title"
    session_llm.assert_called_once_with(
        persona=persona,
        user=user,
        llm_override=override,
        additional_headers={"x-request-id": "naming-request"},
    )
    session_cost.assert_called_once_with(
        db_session=session_factory.return_value.__enter__.return_value,
        tenant_id="naming-tenant",
        llm_provider_api_key="session-key",
    )
    utility_cost.assert_not_called()


@pytest.mark.parametrize("failure_stage", ["cost", "construction"])
def test_configured_utility_failure_returns_text_fallback(
    failure_stage: str, utility_model: ModelConfiguration, naming_llm: MagicMock
) -> None:
    with (
        patch("onyx.server.query_and_chat.chat_backend.check_token_rate_limits"),
        patch("onyx.llm.factory.get_session_with_current_tenant"),
        patch("onyx.llm.factory.fetch_default_model", return_value=utility_model),
        patch("onyx.llm.factory.check_llm_cost_limit_for_provider") as utility_cost,
        patch("onyx.llm.factory.llm_from_provider", return_value=naming_llm) as build,
        patch("onyx.llm.factory.get_current_tenant_id", return_value="naming-tenant"),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_llm_for_persona"
        ) as session_llm,
        patch(
            "onyx.server.query_and_chat.chat_backend.generate_chat_session_name"
        ) as generate,
    ):
        if failure_stage == "cost":
            utility_cost.side_effect = OnyxError(OnyxErrorCode.RATE_LIMITED)
        else:
            build.side_effect = ValueError("Utility model is unavailable")

        title = _generate_or_fallback_chat_session_name(
            chat_history=[_chat_message("Explain usage metering", MessageType.USER)],
            request=Request({"type": "http", "headers": []}),
            user=MagicMock(),
            chat_session_id=uuid4(),
            persona=None,
            llm_override=None,
        )

    assert title == "Explain usage metering"
    utility_cost.assert_called_once()
    if failure_stage == "cost":
        build.assert_not_called()
    else:
        build.assert_called_once()
    session_llm.assert_not_called()
    generate.assert_not_called()
