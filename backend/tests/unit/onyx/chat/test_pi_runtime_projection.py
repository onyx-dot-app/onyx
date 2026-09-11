"""Frequent model events only touch the small projection checkpoint."""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch
from uuid import uuid4

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.emitter import NullEmitter
from onyx.chat.models import StreamingError
from onyx.chat.pi.presentation import ChatPresentation
from onyx.chat.pi.projection import ProjectionSnapshot
from onyx.chat.pi.runtime import apply_operation, execution_error, finish
from onyx.db.models import AgentRun
from onyx.llm.model_response import Delta, ModelResponseStream, StreamingChoice


def test_chunk_batch_does_not_load_inputs_or_construct_domain_host() -> None:
    run = MagicMock(spec=AgentRun)
    run.id = uuid4()
    run.attempt_id = uuid4()
    run.cancel_requested = False
    presenter = ChatPresentation(
        NullEmitter(), ChatStateContainer(), DynamicCitationProcessor(), 0, None, 1.0
    )
    snapshot = ProjectionSnapshot.capture(presenter)
    chunks = [
        ModelResponseStream(
            id="step", created="0", choice=StreamingChoice(delta=Delta(content=text))
        )
        for text in ["Hello", " world."]
    ]
    with (
        patch("onyx.chat.pi.runtime.agent_runs.claim_operation", return_value=run),
        patch("onyx.chat.pi.runtime.agent_runs.require_owner", return_value=run),
        patch("onyx.chat.pi.runtime.StreamEmitter", return_value=NullEmitter()),
        patch("onyx.chat.pi.runtime.load_state", return_value=snapshot) as load,
        patch("onyx.chat.pi.runtime.save_state") as save,
        patch(
            "onyx.chat.pi.inputs.RunInputs.build_host",
            side_effect=AssertionError(
                "Token events must not construct tools or models"
            ),
        ),
    ):
        apply_operation(
            run.id,
            run.attempt_id,
            2,
            "events",
            {
                "events": [
                    {"type": "chunk", "chunk": chunk.model_dump(mode="json")}
                    for chunk in chunks
                ]
            },
        )
    load.assert_called_once_with(run.id, "projection", ProjectionSnapshot)
    assert save.call_count == 1
    saved = save.call_args.args
    assert saved[:2] == (run.id, "projection")
    restored = ProjectionSnapshot.model_validate_json(saved[2].model_dump_json())
    assert restored.answer == "Hello world."
    assert restored.presentation.answer_open


def test_provider_failures_keep_safe_classification_and_retry_guidance() -> None:

    assert execution_error(
        "failed",
        {
            "code": "RATE_LIMIT_ERROR",
            "retryable": True,
            "message": "provider raw response: sensitive prompt",
        },
        details={"model_index": 1, "model": "test-model", "provider": "test-provider"},
    ) == StreamingError(
        error="The model provider rate limit was reached. Please try again later.",
        error_code="RATE_LIMIT_ERROR",
        is_retryable=True,
        details={"model_index": 1, "model": "test-model", "provider": "test-provider"},
    )


def test_queued_cancellation_saves_stop_without_requiring_uncreated_host_snapshot() -> (
    None
):

    run = MagicMock(spec=AgentRun)
    run.id, run.attempt_id, run.chat_session_id = uuid4(), None, uuid4()
    run.group_id, run.model_index, run.message_id = 1, 0, 100
    run.cancel_requested = True
    inputs = MagicMock()
    inputs.record_mode = None
    host = inputs.build_host.return_value
    host.state_container.get_answer_tokens.return_value = None
    with (
        patch("onyx.chat.pi.runtime.agent_runs.begin_finish", return_value=True),
        patch("onyx.chat.pi.runtime.agent_runs.get_run", return_value=run),
        patch(
            "onyx.chat.pi.runtime.agent_runs.complete_run", return_value=False
        ) as complete,
        patch("onyx.chat.pi.runtime.agent_runs.load_message"),
        patch("onyx.chat.pi.runtime.load_state", return_value=inputs),
        patch("onyx.chat.pi.runtime.input_context", return_value=nullcontext()),
        patch("onyx.chat.pi.runtime.state_redis") as redis,
        patch("onyx.chat.pi.runtime.save_state"),
        patch("onyx.chat.pi.runtime.append_packet"),
        patch("onyx.chat.process_message.llm_loop_completion_handle") as persist,
    ):
        redis.return_value.exists.return_value = False
        finish(run.id, None, "cancelled")
    host.restore.assert_not_called()
    persist.assert_called_once()
    assert not persist.call_args.kwargs["is_connected"]()
    complete.assert_called_once_with(run.id, "cancelled")


def test_finalization_failure_identifies_model_when_inputs_are_unavailable() -> None:
    run = MagicMock(spec=AgentRun)
    run.id, run.attempt_id, run.chat_session_id = uuid4(), uuid4(), uuid4()
    run.group_id, run.model_index, run.message_id = 1, 1, 100
    run.cancel_requested = False
    with (
        patch("onyx.chat.pi.runtime.agent_runs.begin_finish", return_value=True),
        patch("onyx.chat.pi.runtime.agent_runs.get_run", return_value=run),
        patch("onyx.chat.pi.runtime.agent_runs.complete_run", return_value=False),
        patch("onyx.chat.pi.runtime.agent_runs.save_failure"),
        patch(
            "onyx.chat.pi.runtime.load_state",
            side_effect=ValueError("sensitive internal failure"),
        ),
        patch("onyx.chat.pi.runtime.state_redis"),
        patch("onyx.chat.pi.runtime.append_packet") as append,
    ):
        finish(run.id, run.attempt_id, "failed")
    assert append.call_args_list[0].args[1] == StreamingError(
        error="Agent execution could not be completed.",
        error_code="AGENT_ERROR",
        is_retryable=False,
        details={"model_index": 1},
    )
