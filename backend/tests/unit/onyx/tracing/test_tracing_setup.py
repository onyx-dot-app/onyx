"""setup_tracing: dynamic processor, user_usage registration, idempotency."""

from unittest.mock import patch

import pytest

from onyx.tracing import setup as tracing_setup
from onyx.tracing.dynamic_processor import DynamicTracingProcessor
from onyx.tracing.provider_config import (
    BraintrustConfig,
    EffectiveTracingConfig,
    LangfuseConfig,
)

RESOLVE = "onyx.tracing.dynamic_processor.resolve_effective_tracing_config"
BUILD = "onyx.tracing.dynamic_processor.build_delegates"


def test_setup_tracing_registers_single_dynamic_processor() -> None:
    tracing_setup._initialized = False
    with (
        patch.object(tracing_setup, "set_trace_processors") as mock_set,
        patch.object(tracing_setup, "_setup_user_usage_tracking"),
        patch.object(tracing_setup, "USER_USAGE_TRACKING_ENABLED", False),
        patch(RESOLVE, return_value=EffectiveTracingConfig()),
        patch(BUILD, return_value=[]),
    ):
        result = tracing_setup.setup_tracing()

        mock_set.assert_called_once()
        (processors,) = mock_set.call_args.args
        assert len(processors) == 1
        assert isinstance(processors[0], DynamicTracingProcessor)
        assert result == []

    tracing_setup._initialized = False


def test_setup_tracing_registers_user_usage_by_default() -> None:
    """Usage tracking is on by default, independent of external backends."""
    tracing_setup._initialized = False
    with (
        patch.object(tracing_setup, "set_trace_processors"),
        patch.object(tracing_setup, "_setup_user_usage_tracking") as mock_setup,
        patch.object(tracing_setup, "USER_USAGE_TRACKING_ENABLED", True),
        patch(RESOLVE, return_value=EffectiveTracingConfig()),
        patch(BUILD, return_value=[]),
    ):
        result = tracing_setup.setup_tracing()
        mock_setup.assert_called_once()
        assert "user_usage" in result

    tracing_setup._initialized = False


def test_setup_tracing_fails_when_usage_recorder_cannot_start() -> None:
    tracing_setup._initialized = False
    with (
        patch.object(tracing_setup, "set_trace_processors"),
        patch.object(
            tracing_setup,
            "_setup_user_usage_tracking",
            side_effect=RuntimeError("recorder unavailable"),
        ),
        patch.object(tracing_setup, "USER_USAGE_TRACKING_ENABLED", True),
        patch(RESOLVE, return_value=EffectiveTracingConfig()),
        patch(BUILD, return_value=[]),
        pytest.raises(RuntimeError, match="recorder unavailable"),
    ):
        tracing_setup.setup_tracing()

    assert tracing_setup._initialized is False


def test_setup_tracing_is_idempotent() -> None:
    tracing_setup._initialized = False
    with (
        patch.object(tracing_setup, "set_trace_processors") as mock_set,
        patch.object(tracing_setup, "_setup_user_usage_tracking"),
        patch(RESOLVE, return_value=EffectiveTracingConfig()),
        patch(BUILD, return_value=[]),
    ):
        tracing_setup.setup_tracing()
        result2 = tracing_setup.setup_tracing()
        assert result2 == []
        mock_set.assert_called_once()

    tracing_setup._initialized = False


def test_setup_tracing_reports_active_providers() -> None:
    config = EffectiveTracingConfig(
        braintrust=BraintrustConfig(api_key="k", project="p"),
        langfuse=LangfuseConfig(secret_key="s", public_key="pk", host=None),
    )
    tracing_setup._initialized = False
    with (
        patch.object(tracing_setup, "set_trace_processors"),
        patch.object(tracing_setup, "_setup_user_usage_tracking"),
        patch.object(tracing_setup, "USER_USAGE_TRACKING_ENABLED", False),
        patch(RESOLVE, return_value=config),
        patch(BUILD, return_value=[]),
    ):
        result = tracing_setup.setup_tracing()
        assert result == ["braintrust", "langfuse"]

    tracing_setup._initialized = False
