"""Synchronous callers consume durable worker output without owning execution."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.models import StreamingError
from onyx.chat.pi.host_state import ChatHostSnapshot, ChatStateSnapshot
from onyx.chat.pi.service import queued_sync
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    OverallStop,
    Packet,
)


def test_model_failure_does_not_hide_another_models_output_or_final_state() -> None:
    setup = MagicMock(chat_session_id=uuid4(), processing_run_id=17)
    run_ids = [uuid4(), uuid4()]
    packets = [
        StreamingError(
            error="Rate limited", error_code="RATE_LIMIT_ERROR", is_retryable=True
        ),
        Packet(
            placement=Placement(turn_index=0, model_index=1),
            obj=AgentResponseDelta(content="Other model answer"),
        ),
        Packet(placement=Placement(turn_index=0, model_index=1), obj=OverallStop()),
    ]
    saved = ChatStateContainer()
    saved.set_answer_tokens("Persisted primary model output")
    snapshot = MagicMock(spec=ChatHostSnapshot)
    snapshot.state = ChatStateSnapshot.capture(saved)
    restored = ChatStateContainer()
    redis = MagicMock()
    redis.lrange.side_effect = [
        [packet.model_dump_json().encode() for packet in packets],
        [],
    ]
    redis.exists.return_value = True
    with (
        patch("onyx.chat.pi.service.prepare_dispatch", return_value=run_ids),
        patch("onyx.chat.pi.service.enqueue", new_callable=AsyncMock) as enqueue,
        patch("onyx.chat.pi.service.state_redis", return_value=redis),
        patch("onyx.chat.pi.service.load_state", return_value=snapshot),
    ):
        result = list(queued_sync(setup, MagicMock(), [], restored))
    assert result == packets
    assert [call.args[0] for call in enqueue.await_args_list] == run_ids
    assert restored.get_answer_tokens() == "Persisted primary model output"


def test_expired_replay_ends_explicitly_instead_of_waiting_forever() -> None:
    redis = MagicMock()
    redis.lrange.return_value = []
    redis.exists.return_value = False
    with (
        patch("onyx.chat.pi.service.prepare_dispatch", return_value=[uuid4()]),
        patch("onyx.chat.pi.service.enqueue", new_callable=AsyncMock),
        patch("onyx.chat.pi.service.state_redis", return_value=redis),
        pytest.raises(RuntimeError, match="stream expired"),
    ):
        list(
            queued_sync(
                MagicMock(chat_session_id=uuid4(), processing_run_id=1),
                MagicMock(),
                [],
                None,
            )
        )
