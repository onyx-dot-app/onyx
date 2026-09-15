"""Verify the main streaming chat flow emits an anonymous ``latency`` record.

The web UI consumes ``handle_stream_message_objects`` directly, so the timing
decorator on that entry point is the only thing standing between a chat turn
and a telemetry record. These tests pin the record type, name, and user id, and
check the record is still sent when the stream fails or the client disconnects.
"""

from collections.abc import Generator
from typing import Any, cast
from unittest.mock import Mock

import pytest

from onyx.chat import process_message
from onyx.chat.models import AnswerStream
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from onyx.utils import timing
from onyx.utils.telemetry import RecordType

_USER_ID = "3f1c9a7e-0f38-4c3d-9a55-2d9e8a1b4c6d"


def _packet() -> MessageResponseIDInfo:
    return MessageResponseIDInfo(user_message_id=1, reserved_assistant_message_id=2)


def _mock_user() -> Mock:
    user = Mock()
    user.id = _USER_ID
    user.is_anonymous = False
    return user


@pytest.fixture
def telemetry_sink(monkeypatch: pytest.MonkeyPatch) -> Mock:
    # The decorator resolves ``optional_telemetry`` from the timing module's
    # namespace, so patch it there rather than in ``onyx.utils.telemetry``.
    sink = Mock(return_value=None)
    monkeypatch.setattr(timing, "optional_telemetry", sink)
    return sink


def _install_turn(monkeypatch: pytest.MonkeyPatch, turn: Any) -> None:
    monkeypatch.setattr(process_message, "_stream_chat_turn", turn)


def _assert_single_latency_record(sink: Mock) -> None:
    assert sink.call_count == 1, sink.call_args_list
    kwargs = sink.call_args.kwargs
    assert kwargs["record_type"] == RecordType.LATENCY
    assert kwargs["user_id"] == _USER_ID
    data = kwargs["data"]
    assert data["function"] == "handle_stream_message_objects"
    float(data["latency"])  # stringified seconds, must parse


def test_streaming_turn_emits_latency_record(
    monkeypatch: pytest.MonkeyPatch, telemetry_sink: Mock
) -> None:
    def fake_turn(**_: Any) -> AnswerStream:
        yield _packet()
        yield _packet()

    _install_turn(monkeypatch, fake_turn)

    stream = process_message.handle_stream_message_objects(
        new_msg_req=SendMessageRequest(message="hello"),
        user=_mock_user(),
    )

    # Nothing is sent until the stream is exhausted: the record covers the turn.
    first = next(stream)
    assert isinstance(first, MessageResponseIDInfo)
    telemetry_sink.assert_not_called()

    remaining = list(stream)
    assert len(remaining) == 1
    _assert_single_latency_record(telemetry_sink)


def test_streaming_turn_emits_latency_record_on_failure(
    monkeypatch: pytest.MonkeyPatch, telemetry_sink: Mock
) -> None:
    def failing_turn(**_: Any) -> AnswerStream:
        yield _packet()
        raise RuntimeError("llm exploded")

    _install_turn(monkeypatch, failing_turn)

    stream = process_message.handle_stream_message_objects(
        new_msg_req=SendMessageRequest(message="hello"),
        user=_mock_user(),
    )

    with pytest.raises(RuntimeError, match="llm exploded"):
        list(stream)

    _assert_single_latency_record(telemetry_sink)


def test_streaming_turn_emits_latency_record_on_client_disconnect(
    monkeypatch: pytest.MonkeyPatch, telemetry_sink: Mock
) -> None:
    def endless_turn(**_: Any) -> Generator[MessageResponseIDInfo, None, None]:
        while True:
            yield _packet()

    _install_turn(monkeypatch, endless_turn)

    stream = cast(
        Generator[Any, None, None],
        process_message.handle_stream_message_objects(
            new_msg_req=SendMessageRequest(message="hello"),
            user=_mock_user(),
        ),
    )
    next(stream)
    # ``StreamingResponse`` closes the generator when the client goes away.
    stream.close()

    _assert_single_latency_record(telemetry_sink)
