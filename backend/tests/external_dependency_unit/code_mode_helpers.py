"""Helpers for code mode tests that run the chat flow against the DB."""

import json
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any
from unittest.mock import patch
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.chat.models import AnswerStreamPart
from onyx.chat.process_message import handle_stream_message_objects
from onyx.db.models import ToolCall, User
from onyx.llm.cancellation import check_cancelled, current_cancellation
from onyx.llm.model_request import ChatCompletionMessage, ToolMessage
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ModelResponseStream,
    ResponseFunctionCall,
)
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.streaming_models import (
    CodeModeDelta,
    CodeModeStart,
    Packet,
)
from onyx.tools.tool_implementations.code_mode.models import CodeModeExecutionResult
from tests.unit.onyx.agents.fakes import ScriptedLLM

# A step is a fixed reply, or a reply built from the prompt.
Step = Delta | Callable[[list[ChatCompletionMessage]], Delta]


class ChatLLM(ScriptedLLM):
    """A scripted model for chat flow tests.

    Step `n` starts only after `gates[n]` returns. With `hold_open`, a request
    after the script keeps the response busy until the response is cancelled.
    """

    def __init__(
        self,
        steps: Sequence[Step],
        *,
        gates: dict[int, Callable[[], None]] | None = None,
        hold_open: bool = False,
    ) -> None:
        super().__init__([], max_input_tokens=128000)
        self.script = list(steps)
        self.gates = gates or {}
        self.hold_open = hold_open

    def stream_raw(
        self, prompt: list[ChatCompletionMessage], *args: Any, **kwargs: Any
    ) -> Iterator[ModelResponseStream]:
        step = len(self.requests)
        if self.hold_open and step >= len(self.script):
            self.requests.append({"prompt": prompt, **kwargs})
            signal = current_cancellation()
            assert signal is not None
            end = time.monotonic() + 60
            while not signal.cancelled and time.monotonic() < end:
                time.sleep(0.05)
            check_cancelled()
            raise AssertionError("The response was not cancelled")
        gate = self.gates.get(step)
        if gate is not None:
            gate()
        reply = self.script[step]
        self.steps = iter([reply if isinstance(reply, Delta) else reply(prompt)])
        yield from super().stream_raw(prompt, *args, **kwargs)


def tool_step(name: str, call_id: str, arguments: dict[str, object]) -> Delta:
    return Delta(
        tool_calls=[
            ChatCompletionDeltaToolCall(
                id=call_id,
                index=0,
                function=ResponseFunctionCall(
                    name=name, arguments=json.dumps(arguments)
                ),
            )
        ]
    )


def code_step(call_id: str, code: str, **arguments: object) -> Delta:
    return tool_step("execute_code", call_id, {"code": code, **arguments})


def wait_step(call_id: str, cell_id: int, **arguments: object) -> Delta:
    return tool_step("wait_code", call_id, {"cell_id": cell_id, **arguments})


def send(
    chat_session_id: UUID,
    user: User,
    llm: ScriptedLLM,
    message: str,
    *,
    code_mode: bool = True,
    on_part: Callable[[AnswerStreamPart], None] = lambda _part: None,
) -> list[AnswerStreamPart]:
    """Send a message and read its stream; `on_part` sees each part as it arrives."""
    parts: list[AnswerStreamPart] = []
    with (
        patch("onyx.chat.agent.CODE_MODE_ENABLED", code_mode),
        patch("onyx.chat.process_message.get_llm_for_persona", return_value=llm),
        patch(
            "onyx.server.features.mcp.ssrf.validate_mcp_outbound_url",
            side_effect=lambda url, **_: url,
        ),
    ):
        for part in handle_stream_message_objects(
            new_msg_req=SendMessageRequest(
                message=message, chat_session_id=chat_session_id, stream=True
            ),
            user=user,
        ):
            parts.append(part)
            on_part(part)
    return parts


def tool_text(prompt: Sequence[ChatCompletionMessage], call_id: str) -> str:
    """The tool result that `prompt` gives the model for `call_id`."""
    [message] = [
        message
        for message in prompt
        if isinstance(message, ToolMessage) and message.tool_call_id == call_id
    ]
    content = message.content
    return content if isinstance(content, str) else "".join(p.text for p in content)


def last_tool_text(llm: ScriptedLLM, call_id: str) -> str:
    """The tool result for `call_id` in the model's last request."""
    return tool_text(llm.requests[-1]["prompt"], call_id)


def saved_cells(
    db_session: Session, chat_session_id: UUID
) -> list[CodeModeExecutionResult]:
    """The saved code mode observations of a chat, in order."""
    db_session.expire_all()
    rows = (
        db_session.query(ToolCall)
        .filter(ToolCall.chat_session_id == chat_session_id)
        .order_by(ToolCall.id)
        .all()
    )
    return [
        row.result.details
        for row in rows
        if row.result is not None
        and isinstance(row.result.details, CodeModeExecutionResult)
    ]


def final_deltas(packets: Sequence[object]) -> list[CodeModeDelta]:
    """The code mode deltas that end an observation or report a closing record."""
    return [
        packet.obj
        for packet in packets
        if isinstance(packet, Packet)
        and isinstance(packet.obj, CodeModeDelta)
        and packet.obj.status is not None
    ]


def code_mode_shape(packets: Sequence[object]) -> list[tuple[str, int, int | None]]:
    """Packet types and placements of the turns that show a code mode block.

    Replay has no streamed tool arguments and sends printed text with the final
    delta, so streamed arguments and stdout-only deltas are left out.
    """
    turns = {
        packet.placement.turn_index
        for packet in packets
        if isinstance(packet, Packet) and isinstance(packet.obj, CodeModeStart)
    }
    return [
        (packet.obj.type, packet.placement.turn_index, packet.placement.sub_turn_index)
        for packet in packets
        if isinstance(packet, Packet)
        and packet.placement.turn_index in turns
        and packet.obj.type != "tool_call_argument_delta"
        and not (isinstance(packet.obj, CodeModeDelta) and packet.obj.status is None)
    ]


def closing_deltas(packets: Sequence[object]) -> list[CodeModeDelta]:
    return [delta for delta in final_deltas(packets) if delta.response_ended]


def assert_cells_released() -> None:
    """No cell driver or nested call thread outlives the response."""
    end = time.monotonic() + 15
    while time.monotonic() < end and code_mode_threads():
        time.sleep(0.1)
    assert not code_mode_threads()


def code_mode_threads() -> list[str]:
    """Names of live cell driver and nested call threads."""
    return [
        thread.name
        for thread in threading.enumerate()
        if thread.name.startswith("code-mode-")
    ]
