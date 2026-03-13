from __future__ import annotations

import os
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.chat.models import AnswerStreamPart
from onyx.chat.models import StreamingError
from onyx.chat.process_message import handle_stream_message_objects
from onyx.db.chat import create_chat_session
from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import fetch_existing_llm_providers
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_llm_provider
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.server.query_and_chat.models import MessageResponseIDInfo
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import Packet
from tests.external_dependency_unit.conftest import create_test_user


def test_answer_with_only_anthropic_provider(
    db_session: Session,
    full_deployment_setup: None,  # noqa: ARG001
    mock_external_deps: None,  # noqa: ARG001
) -> None:
    """Ensure chat still streams answers when only an Anthropic provider is configured."""

    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    assert anthropic_api_key, "ANTHROPIC_API_KEY environment variable must be set"

    # Drop any existing providers so that only Anthropic is available.
    for provider in fetch_existing_llm_providers(db_session, [LLMModelFlowType.CHAT]):
        remove_llm_provider(db_session, provider.id)

    anthropic_model = "claude-haiku-4-5-20251001"
    provider_name = f"anthropic-test-{uuid4().hex}"

    anthropic_provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=provider_name,
            provider=LlmProviderNames.ANTHROPIC,
            api_key=anthropic_api_key,
            is_public=True,
            groups=[],
            model_configurations=[
                ModelConfigurationUpsertRequest(name=anthropic_model, is_visible=True)
            ],
            api_key_changed=True,
        ),
        db_session=db_session,
    )

    try:
        update_default_provider(anthropic_provider.id, anthropic_model, db_session)

        test_user = create_test_user(db_session, email_prefix="anthropic_only")
        chat_session = create_chat_session(
            db_session=db_session,
            description="Anthropic only chat",
            user_id=test_user.id,
            persona_id=0,
        )

        chat_request = SendMessageRequest(
            message="hello",
            chat_session_id=chat_session.id,
        )

        response_stream: list[AnswerStreamPart] = []
        for packet in handle_stream_message_objects(
            new_msg_req=chat_request,
            user=test_user,
            db_session=db_session,
        ):
            response_stream.append(packet)

        assert response_stream, "Should receive streamed packets"
        assert not any(
            isinstance(packet, StreamingError) for packet in response_stream
        ), "No streaming errors expected with Anthropic provider"

        has_message_id = any(
            isinstance(packet, MessageResponseIDInfo) for packet in response_stream
        )
        assert has_message_id, "Should include reserved assistant message ID"

        has_message_start = any(
            isinstance(packet, Packet) and isinstance(packet.obj, AgentResponseStart)
            for packet in response_stream
        )
        assert has_message_start, "Stream should have a MessageStart packet"

        has_message_delta = any(
            isinstance(packet, Packet) and isinstance(packet.obj, AgentResponseDelta)
            for packet in response_stream
        )
        assert has_message_delta, "Stream should have a MessageDelta packet"

    finally:
        remove_llm_provider(db_session, anthropic_provider.id)
