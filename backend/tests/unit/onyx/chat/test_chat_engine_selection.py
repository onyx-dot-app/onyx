"""Both entry points use the deployment engine without automatic fallback."""

import asyncio
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.responses import StreamingResponse

from onyx.chat import process_message
from onyx.chat.chat_state import ChatTurnSetup
from onyx.chat.models import AnswerStreamPart
from onyx.configs.chat_configs import ChatEngine
from onyx.server.query_and_chat import chat_backend
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import OverallStop, Packet


@pytest.mark.parametrize("engine", list(ChatEngine))
def test_api_selects_engine_without_calling_the_other(engine: ChatEngine) -> None:
    message = SendMessageRequest(chat_session_id=uuid4(), message="Hello")
    request = Request({"type": "http", "headers": []})
    response = StreamingResponse(iter(["pi"]))
    with (
        patch.object(chat_backend, "CHAT_ENGINE", engine),
        patch.object(chat_backend, "mt_cloud_telemetry"),
        patch.object(
            chat_backend, "get_hashed_api_key_from_request", return_value=None
        ),
        patch.object(chat_backend, "get_hashed_pat_from_request", return_value=None),
        patch(
            "onyx.chat.pi.service.chat_response",
            new_callable=AsyncMock,
            return_value=response,
        ) as pi,
        patch.object(
            chat_backend,
            "handle_stream_message_objects",
            return_value=iter(
                [Packet(placement=Placement(turn_index=0), obj=OverallStop())]
            ),
        ) as legacy,
    ):

        async def consume() -> list[str | bytes | memoryview]:
            result = await chat_backend.handle_send_chat_message(
                message, request, MagicMock()
            )
            assert isinstance(result, StreamingResponse)
            return [chunk async for chunk in result.body_iterator]

        chunks = asyncio.run(consume())
    if engine == ChatEngine.PI:
        assert chunks == ["pi"]
        pi.assert_awaited_once()
        legacy.assert_not_called()
    else:
        assert len(chunks) == 1 and '"stop"' in str(chunks[0])
        legacy.assert_called_once()
        pi.assert_not_awaited()


@pytest.mark.parametrize("engine", list(ChatEngine))
@pytest.mark.parametrize("deep_research", [False, True])
def test_synchronous_callers_select_engine_and_preserve_deep_research(
    engine: ChatEngine, deep_research: bool
) -> None:
    message = SendMessageRequest(
        chat_session_id=uuid4(), message="Hello", deep_research=deep_research
    )
    setup = MagicMock(spec=ChatTurnSetup)
    setup.new_msg_req = message
    setup.incognito_record_mode = None
    setup.chat_session_id = message.chat_session_id
    setup.processing_run_id = 1
    setup.cache = MagicMock()
    packet = Packet(placement=Placement(turn_index=0), obj=OverallStop())

    def build(**_kwargs: object) -> Generator[AnswerStreamPart, None, ChatTurnSetup]:
        yield from ()
        return setup

    with (
        patch.object(process_message, "CHAT_ENGINE", engine),
        patch.object(process_message, "get_session_with_current_tenant"),
        patch.object(process_message, "build_chat_turn", side_effect=build),
        patch.object(process_message, "StreamBufferWriter"),
        patch.object(
            process_message, "_run_models", return_value=iter([packet])
        ) as legacy,
        patch("onyx.chat.pi.service.queued_sync", return_value=iter([packet])) as pi,
    ):
        assert list(
            process_message.handle_stream_message_objects(message, MagicMock())
        ) == [packet]
    if engine == ChatEngine.PI and not deep_research:
        pi.assert_called_once()
        legacy.assert_not_called()
    else:
        legacy.assert_called_once()
        pi.assert_not_called()
