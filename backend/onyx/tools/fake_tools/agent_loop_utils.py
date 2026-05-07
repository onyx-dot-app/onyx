import time
from collections.abc import Callable

from pydantic import BaseModel

from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ToolCallSimple
from onyx.configs.constants import MessageType
from onyx.deep_research.dr_mock_tools import THINK_TOOL_NAME
from onyx.deep_research.dr_mock_tools import THINK_TOOL_RESPONSE_MESSAGE
from onyx.deep_research.dr_mock_tools import THINK_TOOL_RESPONSE_TOKEN_COUNT
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PacketException
from onyx.server.query_and_chat.streaming_models import StreamingType
from onyx.tools.models import ToolCallKickoff
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SpecialToolCalls(BaseModel):
    think_tool_call: ToolCallKickoff | None = None
    finalize_tool_call: ToolCallKickoff | None = None


def find_special_tool_calls(
    tool_calls: list[ToolCallKickoff],
    finalize_tool_name: str,
) -> SpecialToolCalls:
    """Scan ``tool_calls`` for the think and finalize sentinels."""
    think: ToolCallKickoff | None = None
    finalize: ToolCallKickoff | None = None
    for tc in tool_calls:
        if tc.tool_name == THINK_TOOL_NAME:
            think = tc
        elif tc.tool_name == finalize_tool_name:
            finalize = tc
    return SpecialToolCalls(think_tool_call=think, finalize_tool_call=finalize)


def append_think_tool_messages(
    history: list[ChatMessageSimple],
    think_tool_call: ToolCallKickoff,
    token_counter: Callable[[str], int],
) -> None:
    """Append the assistant tool-call + canned tool-response pair to ``history``."""
    msg_str = think_tool_call.to_msg_str()
    tool_call_token_count = token_counter(msg_str)
    history.append(
        ChatMessageSimple(
            message="",
            token_count=tool_call_token_count,
            message_type=MessageType.ASSISTANT,
            tool_calls=[
                ToolCallSimple(
                    tool_call_id=think_tool_call.tool_call_id,
                    tool_name=think_tool_call.tool_name,
                    tool_arguments=think_tool_call.tool_args,
                    token_count=tool_call_token_count,
                )
            ],
            image_files=None,
        )
    )
    history.append(
        ChatMessageSimple(
            message=THINK_TOOL_RESPONSE_MESSAGE,
            token_count=THINK_TOOL_RESPONSE_TOKEN_COUNT,
            message_type=MessageType.TOOL_CALL_RESPONSE,
            tool_call_id=think_tool_call.tool_call_id,
            image_files=None,
        )
    )


def build_assistant_with_tool_calls(
    tool_calls: list[ToolCallKickoff],
    token_counter: Callable[[str], int],
) -> ChatMessageSimple:
    """Build a single ASSISTANT message bundling N tool calls."""
    tool_calls_simple: list[ToolCallSimple] = []
    for tc in tool_calls:
        msg_str = tc.to_msg_str()
        tool_calls_simple.append(
            ToolCallSimple(
                tool_call_id=tc.tool_call_id,
                tool_name=tc.tool_name,
                tool_arguments=tc.tool_args,
                token_count=token_counter(msg_str),
            )
        )
    return ChatMessageSimple(
        message="",
        token_count=sum(tcs.token_count for tcs in tool_calls_simple),
        message_type=MessageType.ASSISTANT,
        tool_calls=tool_calls_simple,
        image_files=None,
    )


def should_force_finalize(
    start_time: float,
    timeout_seconds: float,
    agent_name: str,
) -> bool:
    """Returns True once the loop has run past ``timeout_seconds``."""
    elapsed = time.monotonic() - start_time
    if elapsed > timeout_seconds:
        logger.info(
            "%s exceeded %ss (elapsed: %.1fs); forcing final answer.",
            agent_name,
            timeout_seconds,
            elapsed,
        )
        return True
    return False


def emit_agent_failure(
    emitter: Emitter,
    placement: Placement,
    agent_name: str,
    exc: Exception,
) -> None:
    """Log with stack trace and emit a streaming PacketException at ``placement``."""
    logger.exception("Error running %s call: %s", agent_name, exc)
    emitter.emit(
        Packet(
            placement=placement,
            obj=PacketException(type=StreamingType.ERROR.value, exception=exc),
        )
    )
