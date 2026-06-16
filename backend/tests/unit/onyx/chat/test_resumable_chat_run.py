from onyx.chat.models import StreamingError
from onyx.chat.process_message import _chat_run_terminal_status
from onyx.chat.process_message import _dump_chat_run_stream_part
from onyx.db.chat_run import CANCELLED
from onyx.db.chat_run import COMPLETED
from onyx.db.chat_run import FAILED
from onyx.server.query_and_chat.models import ActiveChatRun
from onyx.server.query_and_chat.models import ResumeChatRunRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet


def test_dump_chat_run_stream_part_serializes_packets_as_json() -> None:
    packet = Packet(
        placement=Placement(turn_index=0),
        obj=OverallStop(type="stop", stop_reason="user_cancelled"),
    )

    dumped = _dump_chat_run_stream_part(packet)

    assert dumped["placement"]["turn_index"] == 0
    assert dumped["placement"]["tab_index"] == 0
    assert dumped["obj"] == {"type": "stop", "stop_reason": "user_cancelled"}


def test_chat_run_terminal_status_detects_stop_and_error() -> None:
    cancelled_packet = Packet(
        placement=Placement(turn_index=0),
        obj=OverallStop(type="stop", stop_reason="user_cancelled"),
    )
    completed_packet = Packet(
        placement=Placement(turn_index=0),
        obj=OverallStop(type="stop"),
    )
    delta_packet = Packet(
        placement=Placement(turn_index=0),
        obj=AgentResponseDelta(content="hello"),
    )

    assert _chat_run_terminal_status(cancelled_packet) == CANCELLED
    assert _chat_run_terminal_status(completed_packet) == COMPLETED
    assert _chat_run_terminal_status(StreamingError(error="boom")) == FAILED
    assert _chat_run_terminal_status(delta_packet) is None


def test_resume_models_serialize_run_metadata() -> None:
    request = ResumeChatRunRequest(
        run_id="00000000-0000-0000-0000-000000000001",
        after_seq=3,
    )
    active_run = ActiveChatRun(
        run_id="00000000-0000-0000-0000-000000000001",
        assistant_message_id=12,
        status="running",
        latest_seq=4,
    )

    assert str(request.run_id) == "00000000-0000-0000-0000-000000000001"
    assert request.after_seq == 3
    assert active_run.model_dump(mode="json") == {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "assistant_message_id": 12,
        "status": "running",
        "latest_seq": 4,
    }
