from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.chat.models import PromptMetadata
from onyx.chat.session_naming import (
    generate_chat_session_name_or_fallback,
    name_new_chat_session,
)
from onyx.configs.constants import MessageType
from onyx.db.enums import LLMModelFlowType
from onyx.db.models import ChatMessage, LLMProvider, ModelConfiguration
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.llm.models import AssistantMessage, TextContent
from onyx.secondary_llm_flows.chat_session_naming import (
    DEFAULT_CHAT_SESSION_NAME,
    get_fallback_chat_session_name,
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
    user = MagicMock()
    user.id = uuid4()
    get_chat_llm = MagicMock()

    with patch(
        "onyx.chat.session_naming.check_token_rate_limits",
        side_effect=OnyxError(OnyxErrorCode.RATE_LIMITED),
    ):
        generated_name = generate_chat_session_name_or_fallback(
            chat_history=chat_history,
            additional_headers=None,
            user=user,
            chat_session_id=uuid4(),
            get_chat_llm=get_chat_llm,
        )

    assert generated_name == first_user_message
    get_chat_llm.assert_not_called()


def test_configured_naming_model_names_chat_without_session_model(
    utility_model: ModelConfiguration,
    naming_llm: MagicMock,
) -> None:
    first_message = _chat_message("Explain usage metering", MessageType.USER)
    first_message.token_count = 2000
    latest_message = _chat_message("Charge for tokens used", MessageType.ASSISTANT)
    latest_message.token_count = 2000
    oversized_message = _chat_message("A" * 3001, MessageType.USER)
    additional_headers = {"x-request-id": "naming-request"}
    session_llm = MagicMock(side_effect=ValueError("Session model is unavailable"))

    def fetch_default(
        _session: object, flow: LLMModelFlowType
    ) -> ModelConfiguration | None:
        return utility_model if flow == LLMModelFlowType.CHAT_NAMING else None

    with (
        patch("onyx.chat.session_naming.check_token_rate_limits"),
        patch("onyx.llm.factory.get_session_with_current_tenant") as session_factory,
        patch("onyx.llm.factory.fetch_default_model", side_effect=fetch_default),
        patch(
            "onyx.llm.factory.llm_from_provider", return_value=naming_llm
        ) as build_utility,
        patch("onyx.llm.factory.check_llm_cost_limit_for_provider") as utility_cost,
        patch("onyx.llm.factory.get_current_tenant_id", return_value="naming-tenant"),
        patch(
            "onyx.chat.session_naming.check_llm_cost_limit_for_provider"
        ) as session_cost,
        patch(
            "onyx.chat.session_naming.get_llm_token_counter",
            return_value=len,
        ),
        patch("onyx.chat.session_naming.ensure_trace"),
        patch(
            "onyx.chat.session_naming.generate_chat_session_name",
            return_value="Usage metering",
        ) as generate,
    ):
        title = generate_chat_session_name_or_fallback(
            chat_history=[first_message, latest_message, oversized_message],
            additional_headers=additional_headers,
            user=MagicMock(),
            chat_session_id=uuid4(),
            get_chat_llm=session_llm,
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
            AssistantMessage(
                content=[TextContent(text="Charge for tokens used")],
                metadata=PromptMetadata(token_count=2000),
            )
        ],
        llm=naming_llm,
    )


def test_unset_utilities_check_session_provider_cost_once(
    naming_llm: MagicMock,
) -> None:
    naming_llm.config = naming_llm.config.model_copy(update={"api_key": "session-key"})
    user = MagicMock()
    session_llm = MagicMock(return_value=naming_llm)
    additional_headers = {"x-request-id": "naming-request"}

    with (
        patch("onyx.chat.session_naming.check_token_rate_limits"),
        patch("onyx.llm.factory.get_session_with_current_tenant"),
        patch("onyx.llm.factory.fetch_default_model", return_value=None),
        patch("onyx.llm.factory.check_llm_cost_limit_for_provider") as utility_cost,
        patch(
            "onyx.chat.session_naming.get_session_with_current_tenant"
        ) as session_factory,
        patch(
            "onyx.chat.session_naming.get_current_tenant_id",
            return_value="naming-tenant",
        ),
        patch(
            "onyx.chat.session_naming.check_llm_cost_limit_for_provider"
        ) as session_cost,
        patch(
            "onyx.chat.session_naming.check_model_spend_limits"
        ) as session_model_limits,
        patch(
            "onyx.chat.session_naming.get_llm_token_counter",
            return_value=len,
        ),
        patch("onyx.chat.session_naming.ensure_trace"),
        patch(
            "onyx.chat.session_naming.generate_chat_session_name",
            return_value="Session title",
        ),
    ):
        title = generate_chat_session_name_or_fallback(
            chat_history=[_chat_message("Explain usage metering", MessageType.USER)],
            additional_headers=additional_headers,
            user=user,
            chat_session_id=uuid4(),
            get_chat_llm=session_llm,
        )

    assert title == "Session title"
    session_llm.assert_called_once_with()
    session_cost.assert_called_once_with(
        db_session=session_factory.return_value.__enter__.return_value,
        tenant_id="naming-tenant",
        llm_provider_api_key="session-key",
    )
    session_model_limits.assert_called_once_with(
        user, naming_llm.config.model_configuration_id
    )
    utility_cost.assert_not_called()


@pytest.mark.parametrize("failure_stage", ["cost", "construction"])
def test_configured_utility_failure_returns_text_fallback(
    failure_stage: str, utility_model: ModelConfiguration, naming_llm: MagicMock
) -> None:
    session_llm = MagicMock()
    with (
        patch("onyx.chat.session_naming.check_token_rate_limits"),
        patch("onyx.llm.factory.get_session_with_current_tenant"),
        patch("onyx.llm.factory.fetch_default_model", return_value=utility_model),
        patch("onyx.llm.factory.check_llm_cost_limit_for_provider") as utility_cost,
        patch("onyx.llm.factory.llm_from_provider", return_value=naming_llm) as build,
        patch("onyx.llm.factory.get_current_tenant_id", return_value="naming-tenant"),
        patch("onyx.chat.session_naming.generate_chat_session_name") as generate,
    ):
        if failure_stage == "cost":
            utility_cost.side_effect = OnyxError(OnyxErrorCode.RATE_LIMITED)
        else:
            build.side_effect = ValueError("Utility model is unavailable")

        title = generate_chat_session_name_or_fallback(
            chat_history=[_chat_message("Explain usage metering", MessageType.USER)],
            additional_headers=None,
            user=MagicMock(),
            chat_session_id=uuid4(),
            get_chat_llm=session_llm,
        )

    assert title == "Explain usage metering"
    utility_cost.assert_called_once()
    if failure_stage == "cost":
        build.assert_not_called()
    else:
        build.assert_called_once()
    session_llm.assert_not_called()
    generate.assert_not_called()


def test_new_chat_is_named_with_the_turns_model(naming_llm: MagicMock) -> None:
    first_question = _chat_message("Explain usage metering", MessageType.USER)
    chat_session = MagicMock(description=None, incognito_record_mode=None)

    with (
        patch("onyx.chat.session_naming.get_cache_backend"),
        patch("onyx.chat.session_naming.get_session_with_current_tenant"),
        patch(
            "onyx.chat.session_naming.get_chat_session_by_id",
            return_value=chat_session,
        ),
        patch(
            "onyx.chat.session_naming.create_chat_history_chain",
            return_value=[first_question],
        ),
        patch(
            "onyx.chat.session_naming.save_chat_session_name_if_unnamed",
            return_value=True,
        ),
        patch("onyx.chat.session_naming.check_token_rate_limits"),
        patch("onyx.chat.session_naming.get_default_utility_llm", return_value=None),
        patch("onyx.chat.session_naming.get_llm_for_persona") as session_llm,
        patch("onyx.chat.session_naming.get_current_tenant_id"),
        patch("onyx.chat.session_naming.check_llm_cost_limit_for_provider"),
        patch("onyx.chat.session_naming.check_model_spend_limits"),
        patch("onyx.chat.session_naming.get_llm_token_counter", return_value=len),
        patch("onyx.chat.session_naming.ensure_trace"),
        patch(
            "onyx.chat.session_naming.generate_chat_session_name",
            return_value="Usage metering",
        ) as generate,
    ):
        name = name_new_chat_session(
            chat_session_id=uuid4(),
            user=MagicMock(),
            chat_llm=naming_llm,
            additional_headers=None,
        )

    assert name == "Usage metering"
    assert generate.call_args.kwargs["llm"] is naming_llm
    session_llm.assert_not_called()
