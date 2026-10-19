"""Measure logical requests. Content is inspected for presence only and never copied."""

import inspect
import threading
import time
import uuid
from collections.abc import Callable, Generator, Iterator
from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar, cast

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.fleet_telemetry import emit_telemetry, error_category

if TYPE_CHECKING:
    from onyx.chat.models import AnswerStreamPart, StreamingError
    from onyx.server.query_and_chat.streaming_models import Packet

F = TypeVar("F", bound=Callable[..., Any])

_ORIGIN_CHANNELS: dict[str, str] = {
    "api": "api",
    "discordbot": "discord",
    "slackbot": "slack",
}
# OverallStop.stop_reason values written by the chat loop.
_STOP_OUTCOMES: dict[str, str] = {"user_cancelled": "canceled"}
# The chat stream sends a 4xx OnyxError as an error packet with one of these codes.
_CLIENT_ERROR_CODES: frozenset[str] = frozenset(
    code.code for code in OnyxErrorCode if code.status_code < 500
)
# Error packet codes as fleet error categories. Other codes report "internal".
_CHAT_ERROR_CATEGORIES: dict[str, str] = {
    "AUTH_ERROR": "auth",
    "PERMISSION_DENIED": "permission",
    "RATE_LIMIT": "rate_limit",
    "BUDGET_EXCEEDED": "rate_limit",
    "CONNECTION_ERROR": "source_unavailable",
    "SERVICE_UNAVAILABLE": "source_unavailable",
    "BAD_GATEWAY": "source_unavailable",
    "LLM_PROVIDER_ERROR": "source_unavailable",
    "GATEWAY_TIMEOUT": "timeout",
}


class QueryMode(str, Enum):
    CHAT = "chat"
    SEARCH = "search"
    # Runs its own orchestration, so the fleet keeps its latency apart from chat.
    DEEP_RESEARCH = "deep_research"


def _channel(kwargs: dict[str, Any]) -> str:
    request = kwargs.get("new_msg_req")
    if request is None:
        return "web"
    # The origin enum is part of SendMessageRequest, not user text.
    return _ORIGIN_CHANNELS.get(request.origin.value.lower(), "web")


def _mode(kwargs: dict[str, Any]) -> QueryMode:
    request = kwargs.get("new_msg_req")
    if request is not None and request.deep_research:
        return QueryMode.DEEP_RESEARCH
    return QueryMode.CHAT


def _is_answer_text(packet: "Packet") -> bool:
    from onyx.server.query_and_chat.streaming_models import AgentResponseDelta

    return isinstance(packet.obj, AgentResponseDelta) and bool(packet.obj.content)


class QueryToolUsage(str, Enum):
    NONE = "none"
    SEARCH_ONLY = "search_only"
    OTHER_ONLY = "other_only"
    SEARCH_AND_OTHER = "search_and_other"


class QueryObservation:
    def __init__(self, *, channel: str, mode: QueryMode) -> None:
        self.started: float = time.monotonic()
        self.channel: str = channel
        self.mode: QueryMode = mode
        self.first_answer_ms: float | None = None
        self.time_to_results_ms: float | None = None
        # None: the request was rejected before it ran, so there is no query to report.
        self.outcome: str | None = "success"
        self.error_code: str | None = None
        self.writer_owned = False
        self._lock = threading.Lock()
        self._used_search = False
        self._used_other_tool = False
        # Chat-loop LLM calls per model index; model comparisons share one observation.
        self._llm_steps: dict[int, int] = {}
        # Each model's count when it queued its first answer text.
        self._answer_llm_steps: dict[int, int] = {}
        self._answer_model: int | None = None
        self._finished = False

    def llm_step_started(self, *, model_idx: int) -> None:
        with self._lock:
            if self._finished:
                return
            self._llm_steps[model_idx] = self._llm_steps.get(model_idx, 0) + 1

    def packet_queued(self, packet: "Packet", *, model_idx: int) -> None:
        """Runs in the model's worker thread before the writer can read the packet,
        so a first answer keeps the count of the call that produced it."""
        if not _is_answer_text(packet):
            return
        with self._lock:
            if not self._finished:
                self._answer_llm_steps.setdefault(
                    model_idx, self._llm_steps.get(model_idx, 0)
                )

    def _llm_cycles(self) -> int | None:
        """The first answering model's LLM calls up to its first answer text, which
        can come before a tool call; None if that text bypassed the emitter. With no
        answer, the most calls one model made: comparison models run in parallel."""
        if self._answer_model is None:
            return max(self._llm_steps.values(), default=0)
        return self._answer_llm_steps.get(self._answer_model)

    def tool_started(self, *, is_search: bool) -> None:
        with self._lock:
            # Stop-button completion freezes usage while workers wind down.
            if self._finished:
                return
            if is_search:
                self._used_search = True
            else:
                self._used_other_tool = True

    def _tool_usage(self) -> QueryToolUsage:
        if self._used_search:
            return (
                QueryToolUsage.SEARCH_AND_OTHER
                if self._used_other_tool
                else QueryToolUsage.SEARCH_ONLY
            )
        return (
            QueryToolUsage.OTHER_ONLY if self._used_other_tool else QueryToolUsage.NONE
        )

    def observe_packet(self, packet: "AnswerStreamPart") -> None:
        from onyx.chat.models import StreamingError
        from onyx.server.query_and_chat.streaming_models import OverallStop, Packet

        if isinstance(packet, Packet):
            if _is_answer_text(packet):
                self.answer(model_idx=packet.placement.model_index or 0)
            elif isinstance(packet.obj, OverallStop):
                stop_outcome = _STOP_OUTCOMES.get(packet.obj.stop_reason or "")
                if stop_outcome is not None:
                    self.outcome = stop_outcome
        elif isinstance(packet, StreamingError):
            self.error_packet(packet)

    def answer(self, *, model_idx: int) -> None:
        if self.first_answer_ms is None:
            self.first_answer_ms = max(0, (time.monotonic() - self.started) * 1000)
            with self._lock:
                self._answer_model = model_idx

    def results(self) -> None:
        if self.time_to_results_ms is None:
            self.time_to_results_ms = max(0, (time.monotonic() - self.started) * 1000)

    def failed(self, error: BaseException) -> None:
        if isinstance(error, OnyxError) and error.status_code < 500:
            # Bad input or a missing permission is not a failed query.
            self.outcome = None
            return
        self.outcome = "failure"
        self.error_code = error_category(error)

    def error_packet(self, packet: "StreamingError") -> None:
        """Classify a chat error packet by its code. The error text never leaves
        the process."""
        # As in `failed`, a 4xx OnyxError is not a failed query. LLM errors carry
        # details, so a provider's NOT_FOUND is still a failure.
        if (
            packet.error_code in _CLIENT_ERROR_CODES
            and not packet.is_retryable
            and packet.details is None
        ):
            self.outcome = None
            return
        self.outcome = "failure"
        self.error_code = _CHAT_ERROR_CATEGORIES.get(
            packet.error_code or "", "internal"
        )

    def finish(self) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
            tool_usage = self._tool_usage() if self.mode != QueryMode.SEARCH else None
            llm_cycles = self._llm_cycles() if self.mode == QueryMode.CHAT else None
        if self.outcome is None:
            return
        # emit_telemetry never raises, so a stream always finishes normally.
        emit_telemetry(
            "query",
            {
                "query_id": str(uuid.uuid4()),
                "channel": self.channel,
                "mode": self.mode,
                "outcome": self.outcome,
                "first_answer_ms": self.first_answer_ms,
                "time_to_results_ms": self.time_to_results_ms,
                "error_code": self.error_code,
                "tool_usage": tool_usage,
                "llm_cycles": llm_cycles,
            },
        )


def observe_chat_packets(
    packets: Iterator[Any],
    *,
    channel: str,
    observation: QueryObservation | None = None,
) -> Iterator[Any]:
    observation = observation or QueryObservation(channel=channel, mode=QueryMode.CHAT)
    try:
        for packet in packets:
            if not observation.writer_owned:
                observation.observe_packet(packet)
            yield packet
    except GeneratorExit:
        if not observation.writer_owned:
            observation.outcome = "disconnected"
        raise
    except BaseException as error:
        if not observation.writer_owned:
            observation.failed(error)
        raise
    finally:
        if not observation.writer_owned:
            observation.finish()
        try:
            if isinstance(packets, Generator):
                packets.close()
        except Exception:
            pass


def telemetry_chat(function: F) -> F:
    @wraps(function)
    def stream(*args: Any, **kwargs: Any) -> Iterator[Any]:
        try:
            channel = _channel(kwargs)
        except Exception:
            channel = "web"
        observation = QueryObservation(channel=channel, mode=_mode(kwargs))
        yield from observe_chat_packets(
            function(*args, **kwargs, query_observation=observation),
            channel=channel,
            observation=observation,
        )

    return cast(F, stream)


def telemetry_query(*, mode: QueryMode) -> Callable[[F], F]:
    """Decorator for search functions/generators; preserve the callable signature."""

    def decorate(function: F) -> F:
        if inspect.isgeneratorfunction(function):

            @wraps(function)
            def stream(*args: Any, **kwargs: Any) -> Iterator[Any]:
                observation: QueryObservation = QueryObservation(
                    channel="web", mode=mode
                )
                try:
                    for packet in function(*args, **kwargs):
                        # Matched by class name: the EE packet models are not
                        # importable here. No packet text is exported.
                        if type(packet).__name__ == "SearchDocsPacket":
                            observation.results()
                        yield packet
                except GeneratorExit:
                    observation.outcome = "disconnected"
                    raise
                except BaseException as error:
                    observation.failed(error)
                    raise
                finally:
                    observation.finish()

            return cast(F, stream)

        @wraps(function)
        def run(*args: Any, **kwargs: Any) -> Any:
            observation: QueryObservation = QueryObservation(channel="api", mode=mode)
            try:
                result = function(*args, **kwargs)
                observation.results()
                return result
            except BaseException as error:
                observation.failed(error)
                raise
            finally:
                observation.finish()

        return cast(F, run)

    return decorate
