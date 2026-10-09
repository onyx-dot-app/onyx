"""Tests for Craft sandbox provisioning Prometheus metrics.

Values are read through ``REGISTRY.get_sample_value`` rather than collector
internals, so the assertions cover the samples Prometheus actually scrapes.
Metrics are process-global, so every assertion is a delta against a baseline.
"""

from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

from onyx.server.metrics.craft_sandbox import (
    OUTCOME_LABEL_NAME,
    PHASE_LABEL_NAME,
    SandboxProvisionPhase,
    SandboxReadyOutcome,
    _provision_phase_duration,
    _provisions_in_progress,
    _ready_duration,
    observe_sandbox_ready,
    time_provision_phase,
    track_sandbox_provision_in_progress,
)

_READY = "onyx_craft_sandbox_ready_duration_seconds"
_PHASE = "onyx_craft_sandbox_provision_phase_duration_seconds"
_IN_PROGRESS = "onyx_craft_sandbox_provisions_in_progress"


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    """Current value of a sample, treating a not-yet-created series as zero."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _ready_count(outcome: SandboxReadyOutcome) -> float:
    return _sample(f"{_READY}_count", {OUTCOME_LABEL_NAME: outcome.value})


def _ready_sum(outcome: SandboxReadyOutcome) -> float:
    return _sample(f"{_READY}_sum", {OUTCOME_LABEL_NAME: outcome.value})


def _phase_count(phase: SandboxProvisionPhase) -> float:
    return _sample(f"{_PHASE}_count", {PHASE_LABEL_NAME: phase.value})


class TestObserveSandboxReady:
    def test_records_duration_under_its_outcome(self) -> None:
        before_sum = _ready_sum(SandboxReadyOutcome.CREATED)
        before_count = _ready_count(SandboxReadyOutcome.CREATED)

        observe_sandbox_ready(SandboxReadyOutcome.CREATED, 7.5)

        assert _ready_sum(SandboxReadyOutcome.CREATED) == pytest.approx(
            before_sum + 7.5
        )
        assert _ready_count(SandboxReadyOutcome.CREATED) == before_count + 1

    def test_hot_and_cold_paths_are_separate_series(self) -> None:
        """The design rests on this: a millisecond hot path must not pollute the
        cold-provision percentiles."""
        before_hot = _ready_count(SandboxReadyOutcome.ALREADY_RUNNING)
        before_cold = _ready_count(SandboxReadyOutcome.CREATED)

        observe_sandbox_ready(SandboxReadyOutcome.ALREADY_RUNNING, 0.004)

        assert _ready_count(SandboxReadyOutcome.ALREADY_RUNNING) == before_hot + 1
        assert _ready_count(SandboxReadyOutcome.CREATED) == before_cold

    def test_every_outcome_is_recordable(self) -> None:
        for outcome in SandboxReadyOutcome:
            before = _ready_count(outcome)
            observe_sandbox_ready(outcome, 1.0)
            assert _ready_count(outcome) == before + 1

    def test_collector_failure_does_not_propagate(self) -> None:
        """Instrumentation must never be able to break provisioning."""
        with patch.object(
            _ready_duration, "labels", side_effect=RuntimeError("registry exploded")
        ):
            observe_sandbox_ready(SandboxReadyOutcome.CREATED, 1.0)


class TestTimeProvisionPhase:
    def test_records_under_expected_phase(self) -> None:
        before = _phase_count(SandboxProvisionPhase.ENSURE_PAT)

        with time_provision_phase(SandboxProvisionPhase.ENSURE_PAT):
            pass

        assert _phase_count(SandboxProvisionPhase.ENSURE_PAT) == before + 1

    def test_phases_are_separate_series(self) -> None:
        before_other = _phase_count(SandboxProvisionPhase.OPENCODE_SERVE_WAIT)

        with time_provision_phase(SandboxProvisionPhase.POD_CREATE):
            pass

        assert _phase_count(SandboxProvisionPhase.OPENCODE_SERVE_WAIT) == before_other

    def test_records_even_when_block_raises(self) -> None:
        """A phase that failed still consumed the caller's time."""
        before = _phase_count(SandboxProvisionPhase.HISTORY_RESTORE)

        with pytest.raises(RuntimeError):
            with time_provision_phase(SandboxProvisionPhase.HISTORY_RESTORE):
                raise RuntimeError("restore failed")

        assert _phase_count(SandboxProvisionPhase.HISTORY_RESTORE) == before + 1

    def test_every_phase_is_recordable(self) -> None:
        """The label space is closed, so every member must be usable."""
        for phase in SandboxProvisionPhase:
            before = _phase_count(phase)
            with time_provision_phase(phase):
                pass
            assert _phase_count(phase) == before + 1

    def test_collector_failure_does_not_propagate(self) -> None:
        with patch.object(
            _provision_phase_duration,
            "labels",
            side_effect=RuntimeError("registry exploded"),
        ):
            with time_provision_phase(SandboxProvisionPhase.POD_CREATE):
                pass


class TestTimeProvisionPhaseAsDecorator:
    """Methods that own a whole phase claim it by decoration, so the decorator
    form has to survive repeated calls and preserve the wrapped return value."""

    def test_preserves_return_value_and_records_each_call(self) -> None:
        @time_provision_phase(SandboxProvisionPhase.POD_READY_WAIT)
        def wait_for_something() -> bool:
            return True

        before = _phase_count(SandboxProvisionPhase.POD_READY_WAIT)

        assert wait_for_something() is True
        assert wait_for_something() is True

        assert _phase_count(SandboxProvisionPhase.POD_READY_WAIT) == before + 2

    def test_records_and_reraises_when_wrapped_call_raises(self) -> None:
        @time_provision_phase(SandboxProvisionPhase.POD_IP_WAIT)
        def wait_and_fail() -> None:
            raise RuntimeError("timeout")

        before = _phase_count(SandboxProvisionPhase.POD_IP_WAIT)

        with pytest.raises(RuntimeError):
            wait_and_fail()

        assert _phase_count(SandboxProvisionPhase.POD_IP_WAIT) == before + 1


class TestTrackSandboxProvisionInProgress:
    def test_returns_to_baseline_on_success(self) -> None:
        before = _sample(_IN_PROGRESS)

        with track_sandbox_provision_in_progress():
            assert _sample(_IN_PROGRESS) == before + 1

        assert _sample(_IN_PROGRESS) == before

    def test_returns_to_baseline_when_block_raises(self) -> None:
        before = _sample(_IN_PROGRESS)

        with pytest.raises(RuntimeError):
            with track_sandbox_provision_in_progress():
                raise RuntimeError("provision failed")

        assert _sample(_IN_PROGRESS) == before

    def test_does_not_decrement_when_increment_failed(self) -> None:
        """A failed inc must not be followed by a dec, or the gauge drifts
        negative and stays wrong for the life of the process."""
        with patch.object(
            _provisions_in_progress, "inc", side_effect=RuntimeError("boom")
        ):
            with patch.object(_provisions_in_progress, "dec") as mock_dec:
                with track_sandbox_provision_in_progress():
                    pass
                mock_dec.assert_not_called()
