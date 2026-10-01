"""Measure logical requests. Content is inspected for presence only and never copied."""

import inspect
import time
import uuid
from collections.abc import Callable, Generator, Iterator
from functools import wraps
from typing import Any, TypeVar, cast

from onyx.utils.fleet_telemetry import emit_telemetry, error_category
from shared_configs.contextvars import get_current_user_id

F = TypeVar("F", bound=Callable[..., Any])
_QUERY_PREFIX = uuid.uuid4().int & (((1 << 64) - 1) << 64)


def _channel(kwargs: dict[str, Any]) -> str:
    request = kwargs.get("new_msg_req")
    if request is not None:
        # The origin enum is part of SendMessageRequest, not user text.
        origin = request.origin.value
        if origin.lower() == "discordbot":
            return "discord"
        if origin.lower() == "slackbot":
            return "slack"
    return "slack" if kwargs.get("slack_context") is not None else "web"


def _observation(
    channel: str, mode: str, user_id: str | None = None
) -> "QueryObservation | None":
    try:
        return QueryObservation(channel=channel, mode=mode, user_id=user_id)
    except Exception:
        return None


def _user_id() -> str | None:
    try:
        return get_current_user_id()
    except Exception:
        return None


class QueryObservation:
    def __init__(self, *, channel: str, mode: str, user_id: str | None = None) -> None:
        self.started = time.monotonic()
        self.channel = channel
        self.mode = mode
        self.user_id = user_id
        # An in-process monotonic ID avoids UUID entropy reads on request threads.
        self.query_id = str(
            uuid.UUID(int=_QUERY_PREFIX | (time.monotonic_ns() & ((1 << 64) - 1)))
        )
        self.first_answer_ms: float | None = None
        self.time_to_results_ms: float | None = None
        self.outcome = "success"
        self.error_code: str | None = None

    def answer(self) -> None:
        try:
            if self.first_answer_ms is None:
                self.first_answer_ms = max(0, (time.monotonic() - self.started) * 1000)
        except Exception:
            pass

    def results(self) -> None:
        try:
            if self.time_to_results_ms is None:
                self.time_to_results_ms = max(
                    0, (time.monotonic() - self.started) * 1000
                )
        except Exception:
            pass

    def failed(self, error: BaseException | None = None) -> None:
        self.outcome = "failure"
        try:
            self.error_code = error_category(error) if error is not None else "unknown"
        except Exception:
            self.error_code = "unknown"

    def finish(self) -> None:
        try:
            emit_telemetry(
                "query",
                {
                    "query_id": self.query_id,
                    "channel": self.channel,
                    "mode": self.mode,
                    "outcome": self.outcome,
                    "total_ms": max(0, (time.monotonic() - self.started) * 1000),
                    "first_answer_ms": self.first_answer_ms,
                    "time_to_results_ms": self.time_to_results_ms,
                    "request_count": 1,
                    "error_code": self.error_code,
                },
                user_id=self.user_id,
            )
        except Exception:
            pass


def observe_chat_packets(
    packets: Iterator[Any], *, channel: str, user_id: str | None = None
) -> Iterator[Any]:
    from onyx.chat.models import StreamingError
    from onyx.server.query_and_chat.streaming_models import (
        AgentResponseDelta,
        OverallStop,
        Packet,
        PacketException,
    )

    observation = _observation(channel, "chat", user_id)
    if observation is None:
        yield from packets
        return
    try:
        for packet in packets:
            try:
                if isinstance(packet, Packet):
                    if (
                        isinstance(packet.obj, AgentResponseDelta)
                        and packet.obj.content
                    ):
                        observation.answer()
                    elif isinstance(packet.obj, PacketException):
                        observation.failed(packet.obj.exception)
                    elif isinstance(
                        packet.obj, OverallStop
                    ) and packet.obj.stop_reason in {
                        "cancelled",
                        "canceled",
                        "disconnected",
                    }:
                        observation.outcome = (
                            "canceled"
                            if packet.obj.stop_reason != "disconnected"
                            else "disconnected"
                        )
                elif isinstance(packet, StreamingError):
                    # error/error_code fields may contain unrestricted strings.
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
            user_id = get_current_user_id()
            user = kwargs.get("user")
            if user is not None:
                user_id = str(user.id)
        except Exception:
            channel = "web"
            user_id = None
        yield from observe_chat_packets(
            function(*args, **kwargs), channel=channel, user_id=user_id
        )

    return cast(F, stream)


def telemetry_query(*, mode: str) -> Callable[[F], F]:
    """Decorator for search functions/generators; preserve the callable signature."""

    def decorate(function: F) -> F:
        if inspect.isgeneratorfunction(function):

            @wraps(function)
            def stream(*args: Any, **kwargs: Any) -> Iterator[Any]:
                observation = _observation("web", mode, _user_id())
                if observation is None:
                    yield from function(*args, **kwargs)
                    return
                try:
                    for packet in function(*args, **kwargs):
                        # Search packet classes are fixed; no packet text is exported.
                        if type(packet).__name__ in {
                            "SearchErrorPacket",
                            "SearchError",
                        }:
                            observation.failed()
                        elif type(packet).__name__ in {
                            "SearchResultsPacket",
                            "SearchDocsPacket",
                            "SearchDocPacket",
                        }:
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
            observation = _observation("api", mode, _user_id())
            if observation is None:
                return function(*args, **kwargs)
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
