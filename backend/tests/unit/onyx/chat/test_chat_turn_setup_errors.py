"""A chat turn that fails before its message ID is reserved still reports the real cause."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.chat.models import ChatStreamError, MessageResponseIDInfo, StreamingError
from onyx.chat.process_message import build_chat_turn, gather_stream
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.models import SendMessageRequest

_PROCESS_MESSAGE = "onyx.chat.process_message"


def _packets(*packets: object) -> Iterator[object]:
    return iter(packets)


def test_gather_stream_reports_an_error_that_came_before_the_message_id() -> None:
    """The turn loads the LLM and checks access before it reserves the ID, so the
    missing ID is a symptom and the stream error is the cause."""
    stream = _packets(
        StreamingError(
            error="No default LLM model found",
            error_code=OnyxErrorCode.LLM_NOT_CONFIGURED.code,
        )
    )

    with pytest.raises(ChatStreamError) as raised:
        gather_stream(stream)  # ty: ignore[invalid-argument-type]

    assert str(raised.value) == "No default LLM model found"
    assert raised.value.error_code == OnyxErrorCode.LLM_NOT_CONFIGURED.code


def test_gather_stream_names_the_missing_id_when_no_error_came() -> None:
    with pytest.raises(ValueError, match="Message ID is required"):
        gather_stream(_packets())  # ty: ignore[invalid-argument-type]


def test_gather_stream_keeps_a_late_error_on_the_response() -> None:
    stream = _packets(
        MessageResponseIDInfo(user_message_id=1, reserved_assistant_message_id=2),
        StreamingError(error="rate limited", error_code="RATE_LIMIT"),
    )

    response = gather_stream(stream)  # ty: ignore[invalid-argument-type]

    assert response.error_msg == "rate limited"
    assert response.error_code == "RATE_LIMIT"
    assert response.message_id == 2


def test_missing_llm_setup_is_a_classified_error_not_a_bare_value_error() -> None:
    """A bare ValueError reaches the user as an unclassified error, and an admin
    who can fix the LLM setup never learns that it is the problem."""
    chat_session = MagicMock()
    chat_session.project_id = None
    chat_session.llm_override = None
    user = MagicMock()
    user.id = uuid4()
    user.is_anonymous = False
    user.email = "user@test.com"

    with (
        patch(f"{_PROCESS_MESSAGE}.get_current_tenant_id", return_value="tenant_a"),
        patch(f"{_PROCESS_MESSAGE}.get_chat_session_by_id", return_value=chat_session),
        patch(f"{_PROCESS_MESSAGE}.mt_cloud_telemetry"),
        patch(
            f"{_PROCESS_MESSAGE}.get_llm_for_persona",
            side_effect=ValueError("No default LLM model found"),
        ),
        pytest.raises(OnyxError) as raised,
    ):
        next(
            build_chat_turn(
                new_msg_req=SendMessageRequest(
                    message="hello", chat_session_id=uuid4()
                ),
                user=user,
                db_session=MagicMock(),
                llm_overrides=None,
            )
        )

    assert raised.value.error_code is OnyxErrorCode.LLM_NOT_CONFIGURED
    assert raised.value.detail == "No default LLM model found"
