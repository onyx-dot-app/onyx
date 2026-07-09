"""Unit tests for LangfuseTracingProcessor metadata handling."""

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock

from onyx.tracing.langfuse_tracing_processor import LangfuseTracingProcessor


def _make_trace(metadata: Mapping[str, Any]) -> MagicMock:
    trace = MagicMock()
    trace.trace_id = "trace-123"
    trace.name = "run_llm_loop"
    trace.export.return_value = {"metadata": metadata}
    return trace


def _make_client_with_observation() -> tuple[MagicMock, MagicMock]:
    observation = MagicMock()
    observation.trace_id = "lf-trace-1"
    observation.id = "lf-span-1"
    client = MagicMock()
    client.start_observation.return_value = observation
    return client, observation


def test_on_trace_start_promotes_user_id_and_session_id() -> None:
    """user_id and chat_session_id in metadata must be passed as first-class
    fields on update_trace so Langfuse populates the Users and Sessions views.
    """
    client, observation = _make_client_with_observation()
    processor = LangfuseTracingProcessor(client=client)

    metadata = {
        "tenant_id": "tenant-abc",
        "chat_session_id": "session-xyz",
        "user_id": "user-42",
    }
    processor.on_trace_start(_make_trace(metadata))

    observation.update_trace.assert_called_once()
    kwargs = observation.update_trace.call_args.kwargs
    assert kwargs["user_id"] == "user-42"
    assert kwargs["session_id"] == "session-xyz"
    assert kwargs["name"] == "run_llm_loop"
    assert kwargs["metadata"] == metadata


def test_on_trace_start_user_id_missing_passes_none() -> None:
    """Anonymous / unattributed traces still update successfully with user_id=None."""
    client, observation = _make_client_with_observation()
    processor = LangfuseTracingProcessor(client=client)

    metadata = {"tenant_id": "tenant-abc", "chat_session_id": "session-xyz"}
    processor.on_trace_start(_make_trace(metadata))

    kwargs = observation.update_trace.call_args.kwargs
    assert kwargs["user_id"] is None
    assert kwargs["session_id"] == "session-xyz"


def test_on_trace_start_coerces_non_string_user_id() -> None:
    """User ids that arrive as ints (e.g. from User.id) are coerced to strings."""
    client, observation = _make_client_with_observation()
    processor = LangfuseTracingProcessor(client=client)

    metadata = {"chat_session_id": "session-xyz", "user_id": 7}
    processor.on_trace_start(_make_trace(metadata))

    kwargs = observation.update_trace.call_args.kwargs
    assert kwargs["user_id"] == "7"
