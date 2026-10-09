"""Measure logical requests. Content is inspected for presence only and never copied."""

import inspect
import time
import uuid
from collections.abc import Callable, Generator, Iterator
from functools import wraps
from typing import Any, TypeVar, cast

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.fleet_telemetry import emit_telemetry, error_category

F = TypeVar("F", bound=Callable[..., Any])

_ORIGIN_CHANNELS: dict[str, str] = {
    "api": "api",
    "discordbot": "discord",
    "slackbot": "slack",
}
# OverallStop.stop_reason values written by the chat loop.
_STOP_OUTCOMES: dict[str, str] = {"user_cancelled": "canceled"}


def _channel(kwargs: dict[str, Any]) -> str:
    request = kwargs.get("new_msg_req")
    if request is None:
        return "web"
    # The origin enum is part of SendMessageRequest, not user text.
    return _ORIGIN_CHANNELS.get(request.origin.value.lower(), "web")


class QueryObservation:
    def __init__(self, *, channel: str, mode: str) -> None:
        self.started: float = time.monotonic()
        self.channel: str = channel
        self.mode: str = mode
        self.first_answer_ms: float | None = None
        self.time_to_results_ms: float | None = None
        # None: the request was rejected before it ran, so there is no query to report.
        self.outcome: str | None = "success"
        self.error_code: str | None = None

    def answer(self) -> None:
        if self.first_answer_ms is None:
            self.first_answer_ms = max(0, (time.monotonic() - self.started) * 1000)

    def results(self) -> None:
        if self.time_to_results_ms is None:
            self.time_to_results_ms = max(0, (time.monotonic() - self.started) * 1000)

    def failed(self, error: BaseException | None = None) -> None:
        if isinstance(error, OnyxError) and error.status_code < 500:
            # Bad input or a missing permission is not a failed query.
            self.outcome = None
            return
        self.outcome = "failure"
        self.error_code = error_category(error) if error is not None else "unknown"

    def finish(self) -> None:
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
            },
        )


def observe_chat_packets(packets: Iterator[Any], *, channel: str) -> Iterator[Any]:
    from onyx.chat.models import StreamingError
    from onyx.server.query_and_chat.streaming_models import (
        AgentResponseDelta,
        OverallStop,
        Packet,
    )

    observation: QueryObservation = QueryObservation(channel=channel, mode="chat")
    try:
        for packet in packets:
            try:
                if isinstance(packet, Packet):
                    if (
                        isinstance(packet.obj, AgentResponseDelta)
                        and packet.obj.content
                    ):
                        observation.answer()
                    elif isinstance(packet.obj, OverallStop):
                        stop_outcome: str | None = _STOP_OUTCOMES.get(
                            packet.obj.stop_reason or ""
                        )
                        if stop_outcome is not None:
                            observation.outcome = stop_outcome
                elif isinstance(packet, StreamingError):
                    # Only the code is read. The error text never leaves the process.
                    if packet.error_code == OnyxErrorCode.QUERY_REJECTED.code:
                        # A query-processing hook refused the query before it ran.
                        observation.outcome = None
                    else:
                        observation.failed()
            except Exception:
                pass
            yield packet
    except GeneratorExit:
        observation.outcome = "disconnected"
        raise
    except BaseException as error:
        observation.failed(error)
        raise
    finally:
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
        yield from observe_chat_packets(function(*args, **kwargs), channel=channel)

    return cast(F, stream)


def telemetry_query(*, mode: str) -> Callable[[F], F]:
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
