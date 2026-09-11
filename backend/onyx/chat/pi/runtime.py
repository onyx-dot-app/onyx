"""Short-lived, fenced Onyx callbacks for independently scheduled Pi runs."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_processing_checker import (
    release_processing_run,
)
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter
from onyx.chat.models import StreamingError
from onyx.chat.pi.chat import ChatHost
from onyx.chat.pi.client import build_start
from onyx.chat.pi.host_state import ChatHostSnapshot
from onyx.chat.pi.input_storage import load_run_inputs
from onyx.chat.pi.inputs import RunInputs
from onyx.chat.pi.models import PiToolCall, PiToolResult
from onyx.chat.pi.projection import ProjectionSnapshot
from onyx.chat.pi.storage import (
    append_packet,
    finish_stream,
    load_state,
    run_key,
    save_state,
    state_redis,
    stream_key,
)
from onyx.configs.app_configs import MOCK_LLM_RESPONSE
from onyx.db import agent_runs
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import AgentRun
from onyx.llm.model_response import ModelResponseStream
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    OverallStop,
    Packet,
)
from onyx.tracing.framework.create import ChatTraceMetadata, trace
from shared_configs.contextvars import (
    CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR,
    CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR,
    CURRENT_USAGE_CREDENTIAL_CONTEXTVAR,
    CURRENT_USER_ID_CONTEXTVAR,
)


@contextmanager
def input_context(inputs: RunInputs) -> Iterator[None]:
    mode = inputs.record_mode
    mode_token = CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.set(
        mode.value if mode else None
    )
    session_token = CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.set(
        str(inputs.session_id) if not record_mode_persists_content(mode) else None
    )
    user_token = CURRENT_USER_ID_CONTEXTVAR.set(str(inputs.user_id))
    credential_token = CURRENT_USAGE_CREDENTIAL_CONTEXTVAR.set(inputs.usage_credential)
    try:
        with trace(
            "pi_chat",
            group_id=str(inputs.session_id),
            metadata=ChatTraceMetadata(
                chat_session_id=str(inputs.session_id),
                user_id=str(inputs.user_id),
            ).model_dump(),
        ):
            yield
    finally:
        CURRENT_USAGE_CREDENTIAL_CONTEXTVAR.reset(credential_token)
        CURRENT_USER_ID_CONTEXTVAR.reset(user_token)
        CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.reset(session_token)
        CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.reset(mode_token)


class StreamEmitter(Emitter):
    """Tool progress is published directly; no unbounded intermediate queue."""

    def __init__(self, run: AgentRun, *, check_owner: bool = True) -> None:
        self.run = run
        self.key = stream_key(run.chat_session_id, run.group_id)
        self.check_owner = check_owner
        self.checked_at = 0.0

    def emit(self, packet: Packet) -> None:
        if self.check_owner and time.monotonic() - self.checked_at > 0.5:
            assert self.run.attempt_id is not None
            agent_runs.require_owner(self.run.id, self.run.attempt_id)
            self.checked_at = time.monotonic()
        placement = packet.placement or Placement(turn_index=0)
        append_packet(
            self.key,
            Packet(
                placement=placement.model_copy(
                    update={"model_index": self.run.model_index}
                ),
                obj=packet.obj,
            ),
        )


def claim(run_id: UUID, attempt_id: UUID) -> dict[str, Any]:
    if not agent_runs.claim_run(run_id, attempt_id):
        return {"status": "unavailable"}
    try:
        run = agent_runs.get_run(run_id)
        inputs = load_run_inputs(run)
        with input_context(inputs):
            host = inputs.build_host(StreamEmitter(run))
            save_state(run_id, "host", host.snapshot())
            return {
                "start": build_start(
                    host.llm,
                    str(inputs.session_id),
                    inputs.reasoning_effort,
                    inputs.user_identity,
                    inputs.request.mock_llm_response or MOCK_LLM_RESPONSE,
                )
            }
    except Exception:
        finish(run_id, attempt_id, "failed")
        raise


def _merge_projection(run_id: UUID, host: ChatHost) -> None:
    if state_redis().exists(run_key(run_id, "projection")):
        projection = load_state(run_id, "projection", ProjectionSnapshot)
        host.presenter = projection.restore(host.emitter, host.state_container)
        host.citation_processor = host.presenter.citations


class ModelStreamProjection:
    """Retain only rendering state while the asynchronous HTTP request is open."""

    def __init__(self, run: AgentRun) -> None:
        self.run = run
        self.emitter = StreamEmitter(run, check_owner=False)
        snapshot = load_state(run.id, "projection", ProjectionSnapshot)
        self.presenter = snapshot.restore(self.emitter, ChatStateContainer())
        self.ended = False
        self.saved_at = time.monotonic()
        self.checked_at = time.monotonic()

    @classmethod
    def claim(
        cls, run_id: UUID, attempt_id: UUID, sequence: int
    ) -> "ModelStreamProjection":
        run = agent_runs.claim_operation(run_id, attempt_id, sequence)
        return cls(run)

    def check_owner(self) -> None:
        assert self.run.attempt_id is not None
        agent_runs.require_owner(self.run.id, self.run.attempt_id)
        self.checked_at = time.monotonic()

    def feed(self, events: list[dict[str, Any]]) -> None:
        if time.monotonic() - self.checked_at >= 2:
            self.check_owner()
        for event in events:
            match event["type"]:
                case "chunk":
                    if self.ended:
                        raise ValueError("Model chunk arrived after model_end")
                    self.presenter.feed(
                        ModelResponseStream.model_validate(event["chunk"])
                    )
                case "model_end":
                    if self.ended:
                        raise ValueError("Duplicate model_end")
                    self.ended = True
                case "done":
                    pass
                case _:
                    raise ValueError("Unknown agent stream event")
        if not self.ended and time.monotonic() - self.saved_at >= 0.25:
            save_state(
                self.run.id, "projection", ProjectionSnapshot.capture(self.presenter)
            )
            self.saved_at = time.monotonic()

    def checkpoint(self) -> None:
        self.check_owner()
        projection = ProjectionSnapshot.capture(self.presenter)
        if not self.ended:
            save_state(self.run.id, "projection", projection)
            return
        inputs = load_run_inputs(self.run)
        with input_context(inputs):
            host = inputs.build_host(self.emitter)
            host.restore(load_state(self.run.id, "host", ChatHostSnapshot))
            host.presenter = projection.restore(self.emitter, host.state_container)
            host.citation_processor = host.presenter.citations
            host.feed_step([], finish=True)
            self.check_owner()
            save_state(self.run.id, "host", host.snapshot())
            state_redis().delete(run_key(self.run.id, "projection"))


def _apply_events(run: AgentRun, payload: dict[str, Any]) -> None:
    events = payload["events"]
    if all(event["type"] == "done" for event in events):
        return
    projection = ModelStreamProjection(run)
    projection.feed(events)
    projection.checkpoint()


def apply_operation(
    run_id: UUID,
    attempt_id: UUID,
    sequence: int,
    event_type: str,
    payload: dict[str, Any],
) -> Any:
    run = agent_runs.claim_operation(run_id, attempt_id, sequence)
    if event_type == "events":
        _apply_events(run, payload)
        return None
    inputs = load_run_inputs(run)
    with input_context(inputs):
        host = inputs.build_host(StreamEmitter(run))
        host.restore(load_state(run_id, "host", ChatHostSnapshot))
        value: Any = None
        match event_type:
            case "prepare":
                value = host.prepare_step(int(payload["cycle"]))
            case "model_start":
                host.feed_step([])
                start = build_start(
                    host.llm,
                    str(inputs.session_id),
                    inputs.reasoning_effort,
                    inputs.user_identity,
                )
                host.state_container.set_request_params(
                    {
                        "model": host.llm.config.model_name,
                        "model_provider": host.llm.config.model_provider,
                        "reasoning_effort": start["reasoningEffort"],
                        "agent_sdk": "pi",
                    }
                )
                assert host.presenter is not None
                agent_runs.require_owner(run_id, attempt_id)
                save_state(
                    run_id, "projection", ProjectionSnapshot.capture(host.presenter)
                )
                return None
            case "tools":
                value = host.execute_tools(
                    [PiToolCall.model_validate(call) for call in payload["calls"]]
                )
            case "turn_end":
                host.record_turn(
                    [
                        PiToolResult.model_validate(result)
                        for result in payload["results"]
                    ]
                )
            case _:
                raise ValueError("Unknown agent callback")
        agent_runs.require_owner(run_id, attempt_id)
        save_state(run_id, "host", host.snapshot())
        return value


def execution_error(
    status: str,
    error: dict[str, Any] | None,
    *,
    details: dict[str, str | int] | None = None,
) -> StreamingError:
    """Expose classified guidance without leaking raw provider response bodies."""
    if status == "interrupted":
        return StreamingError(
            error="Agent execution was interrupted.",
            error_code="AGENT_INTERRUPTED",
            is_retryable=False,
            details=details,
        )
    code = str((error or {}).get("code", "AGENT_ERROR"))
    messages = {
        "AUTHENTICATION_ERROR": "The model provider rejected its credentials. Check the provider configuration.",
        "RATE_LIMIT_ERROR": "The model provider rate limit was reached. Please try again later.",
        "CONTEXT_WINDOW_EXCEEDED": "The conversation exceeds the model context window. Start a new chat or select a model with a larger context window.",
        "MODEL_ERROR": "The model provider could not complete this request. Please try again.",
    }
    return StreamingError(
        error=messages.get(code, "The model encountered an error."),
        error_code=code,
        is_retryable=(error or {}).get("retryable") is True,
        details=details,
    )


def finish(
    run_id: UUID,
    attempt_id: UUID | None,
    status: str,
    error: dict[str, Any] | None = None,
    *,
    observed_updated_at: datetime | None = None,
) -> None:
    from onyx.chat.process_message import llm_loop_completion_handle

    if not agent_runs.begin_finish(
        run_id, attempt_id, observed_updated_at=observed_updated_at
    ):
        return
    run = agent_runs.get_run(run_id)
    if run.cancel_requested:
        status = "cancelled"
    key = stream_key(run.chat_session_id, run.group_id)
    content_free = True
    error_details: dict[str, str | int] = {"model_index": run.model_index}
    try:
        inputs = load_run_inputs(run)
        content_free = not record_mode_persists_content(inputs.record_mode)
        error_details.update(
            model=inputs.model.model_name, provider=inputs.model.model_provider
        )
        with input_context(inputs):
            host = inputs.build_host(StreamEmitter(run, check_owner=False))
            if state_redis().exists(run_key(run_id, "host")):
                host.restore(load_state(run_id, "host", ChatHostSnapshot))
            elif status == "completed":
                raise ValueError("Completed run has no final checkpoint")
            _merge_projection(run_id, host)
            if status == "completed":
                host.validate_final_response()
            elif status != "cancelled":
                append_packet(
                    key, execution_error(status, error, details=error_details)
                )
            if (
                status == "completed"
                or status == "cancelled"
                or host.state_container.get_answer_tokens()
            ):
                llm_loop_completion_handle(
                    state_container=host.state_container,
                    is_connected=lambda: status != "cancelled",
                    assistant_message=agent_runs.load_message(run.message_id),
                    llm=host.llm,
                    reserved_tokens=inputs.reserved_tokens,
                    run_compression=status == "completed" and run.model_index == 0,
                    compression_max_input_tokens=inputs.compression_window,
                )
            else:
                agent_runs.save_failure(
                    run.message_id, execution_error(status, error).error
                )
            # Non-streaming internal callers can read this bounded final snapshot.
            save_state(run_id, "result", host.snapshot())
            if content_free:
                state_redis().expire(run_key(run_id, "result"), 30)
    except Exception:
        from onyx.utils.logger import setup_logger

        setup_logger().exception("Could not finalize agent run %s", run_id)
        status = "failed"
        agent_runs.save_failure(
            run.message_id, "Agent execution could not be completed."
        )
        append_packet(
            key,
            StreamingError(
                error="Agent execution could not be completed.",
                error_code="AGENT_ERROR",
                is_retryable=False,
                details=error_details,
            ),
        )
    finally:
        state_redis().delete(
            run_key(run_id, "inputs"),
            run_key(run_id, "host"),
            run_key(run_id, "projection"),
        )
        append_packet(
            key,
            Packet(
                placement=Placement(turn_index=0, model_index=run.model_index),
                obj=OverallStop(
                    stop_reason="user_cancelled"
                    if status == "cancelled"
                    else "finished"
                ),
            ),
        )
        if agent_runs.complete_run(run_id, status):
            cache = get_cache_backend()
            release_processing_run(run.chat_session_id, cache, run.group_id)
            finish_stream(key, content_free=content_free)
            agent_runs.mark_group_stream_closed(run.chat_session_id, run.group_id)
