"""Live, resumable output of background subagent runs.

A background run's events do not reach its parent's stream. Each such run
writes its own packets into a stream buffer in the shared cache, keyed by its
agent's chat session, so any pod can serve them as the root's resume route
serves the root turn.
"""

import threading
import time
from collections.abc import Mapping
from uuid import UUID

from pydantic import BaseModel, ValidationError

from onyx.agents.events import AgentEndEvent, AgentEvent, ToolStartEvent
from onyx.agents.runtime import Run
from onyx.cache.interface import CacheBackend
from onyx.chat.emitter import Emitter
from onyx.chat.presentation import ResponsePresenter, overall_stop
from onyx.chat.stream_buffer import StreamBufferWriter
from onyx.configs.chat_configs import CHAT_STREAM_BUFFER_TTL_S
from onyx.db.chat_response import read_suspended_response_replay
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.utils import get_json_line
from onyx.utils.logger import setup_logger

logger = setup_logger()

_POINTER_PREFIX = "chatagentstream"
_FLUSH_INTERVAL_S = 0.25
# The pointer lives as long as the buffer; the ticker renews it this often.
_POINTER_RENEW_INTERVAL_S = 60.0


class AgentStreamPointer(BaseModel):
    """The live stream of a background run, and the tool call it last started."""

    stream_id: int
    activity_tool: str | None = None


def _pointer_key(response_id: int) -> str:
    return f"{_POINTER_PREFIX}_{response_id}"


def read_agent_stream_pointer(
    cache: CacheBackend, response_id: int
) -> AgentStreamPointer | None:
    raw = cache.get(_pointer_key(response_id))
    if raw is None:
        return None
    try:
        return AgentStreamPointer.model_validate_json(raw)
    except ValidationError:
        logger.warning("Agent stream pointer of response %d is corrupt", response_id)
        return None


def is_background_run(run: Run) -> bool:
    """A child run whose events do not reach its parent's listeners."""
    delivery = run.event_delivery
    return (
        run.snapshot(include_children=False).parent_run_id is not None
        and delivery is not None
        and not delivery.forwards_to_parent
    )


class BackgroundRunStream:
    """Write one execution of a background run into a resumable stream buffer.

    A resumed run first sends its saved output, so the stream always holds the
    whole response. Cache failures make the stream non-resumable; they never
    reach the run.
    """

    def __init__(
        self,
        cache: CacheBackend,
        tenant_id: str,
        run: Run,
        tool_ids: Mapping[str, int | None],
    ) -> None:
        self._cache = cache
        self._response_id = int(run.id)
        self._run_id = run.id
        self.stream_id = time.time_ns() // 1_000_000
        self._buffer = StreamBufferWriter(
            cache=cache,
            chat_session_id=UUID(run.agent_id),
            stream_id=self.stream_id,
        )
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._activity_tool: str | None = None
        self._presenter = ResponsePresenter(Emitter(self._write), tool_ids=tool_ids)
        self._buffer.open()
        self._write_pointer()
        if run.snapshot(include_children=False).steps:
            self._replay_saved(tenant_id)
        self._unsubscribe = run.subscribe(self._consume)
        threading.Thread(
            target=self._tick, name="agent-stream-flush", daemon=True
        ).start()

    def _replay_saved(self, tenant_id: str) -> None:
        try:
            with get_session_with_tenant(tenant_id=tenant_id) as session:
                execution, replay = read_suspended_response_replay(
                    session, self._response_id
                )
            self._presenter.replay(execution.response, replay, execution.presentation)
        except Exception:
            logger.exception(
                "Saved output of agent response %d could not open its stream",
                self._response_id,
            )
            with self._lock:
                self._buffer.mark_truncated()

    def _write(self, packet: Packet) -> None:
        line = get_json_line(packet.model_dump())
        with self._lock:
            self._buffer.append_line(line)

    def _consume(self, event: AgentEvent) -> None:
        if self._closed.is_set():
            return
        self._presenter.consume(event)
        if event.run_id != self._run_id:
            return
        if isinstance(event, ToolStartEvent):
            self._activity_tool = event.tool_call.name
            self._write_pointer()
        elif isinstance(event, AgentEndEvent):
            # The presenter ends only top-level responses; this run has a parent.
            self._write(
                Packet(
                    placement=Placement(turn_index=0),
                    obj=overall_stop(event.outcome, event.failure),
                )
            )
            with self._lock:
                self._buffer.mark_done()

    def _write_pointer(self) -> None:
        try:
            self._cache.set(
                _pointer_key(self._response_id),
                AgentStreamPointer(
                    stream_id=self.stream_id, activity_tool=self._activity_tool
                ).model_dump_json(),
                ex=CHAT_STREAM_BUFFER_TTL_S,
            )
        except Exception:
            logger.exception(
                "Agent stream pointer of response %d could not be saved",
                self._response_id,
            )

    def _tick(self) -> None:
        renewed = time.monotonic()
        while not self._closed.wait(_FLUSH_INTERVAL_S):
            with self._lock:
                self._buffer.flush()
            if time.monotonic() - renewed >= _POINTER_RENEW_INTERVAL_S:
                self._write_pointer()
                renewed = time.monotonic()

    def close(self) -> None:
        """End the stream when its run releases ownership: after its terminal
        save, or when it suspends or fails to start."""
        if self._closed.is_set():
            return
        self._closed.set()
        self._unsubscribe()
        with self._lock:
            self._buffer.mark_done()
        try:
            self._cache.delete(_pointer_key(self._response_id))
        except Exception:
            logger.exception(
                "Agent stream pointer of response %d could not be deleted",
                self._response_id,
            )
