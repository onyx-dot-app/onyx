"""Prometheus metrics for Craft sandbox provisioning latency.

Tracks how long a caller waits for a ready sandbox, and where that time went.

The ``outcome`` label is load-bearing rather than descriptive: obtaining a sandbox
takes milliseconds when the pod is already running and seconds when it has to be
provisioned, so collapsing those into one series would make every percentile
meaningless.
"""

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from enum import Enum

from prometheus_client import Gauge, Histogram

logger = logging.getLogger(__name__)


class SandboxReadyOutcome(str, Enum):
    """Which path produced the sandbox."""

    ALREADY_RUNNING = "already_running"
    CREATED = "created"
    # Row existed in a re-provisionable status (SLEEPING/TERMINATED/FAILED).
    REVIVED = "revived"
    # Row claimed RUNNING but the pod was gone or unhealthy.
    RECOVERED = "recovered"
    FAILED = "failed"


class SandboxProvisionPhase(str, Enum):
    """Closed set of phase labels, so cardinality has one source of truth.

    Each phase is emitted only by the layer that has it; the Docker backend never
    reports the pod-level ones.
    """

    # Backend-agnostic lifecycle.
    PROVISIONING_WAIT = "provisioning_wait"
    HEALTH_CHECK = "health_check"
    ENSURE_PAT = "ensure_pat"
    HYDRATE_MANAGED_CONTENT = "hydrate_managed_content"

    # Kubernetes pod provisioning.
    OPENCODE_SECRET = "opencode_secret"
    POD_CREATE = "pod_create"
    SERVICE_ENSURE = "service_ensure"
    POD_IP_WAIT = "pod_ip_wait"
    HISTORY_RESTORE = "history_restore"
    POD_READY_WAIT = "pod_ready_wait"

    # Both sandbox backends.
    OPENCODE_SERVE_WAIT = "opencode_serve_wait"


OUTCOME_LABEL_NAME = "outcome"
PHASE_LABEL_NAME = "phase"

# Reaches well past the 10s ceiling of the FastAPI instrumentator's per-handler
# histogram, which is why request duration alone cannot measure provisioning.
_PROVISION_DURATION_BUCKETS = (
    0.25,
    0.5,
    1.0,
    2.0,
    3.0,
    5.0,
    7.5,
    10.0,
    15.0,
    20.0,
    30.0,
    45.0,
    60.0,
    120.0,
)

_ready_duration = Histogram(
    "onyx_craft_sandbox_ready_duration_seconds",
    "Time from requesting a Craft sandbox to it being ready, by which path was taken.",
    [OUTCOME_LABEL_NAME],
    buckets=_PROVISION_DURATION_BUCKETS,
)

_provision_phase_duration = Histogram(
    "onyx_craft_sandbox_provision_phase_duration_seconds",
    "Duration of an individual Craft sandbox provisioning phase.",
    [PHASE_LABEL_NAME],
    buckets=_PROVISION_DURATION_BUCKETS,
)

_provisions_in_progress = Gauge(
    "onyx_craft_sandbox_provisions_in_progress",
    "Number of Craft sandbox provisions currently in flight.",
)


def observe_sandbox_ready(outcome: SandboxReadyOutcome, duration_s: float) -> None:
    """Records a completed attempt to obtain a ready sandbox."""
    try:
        _ready_duration.labels(outcome=outcome.value).observe(duration_s)
    except Exception:
        logger.warning("Failed to record sandbox readiness metric.", exc_info=True)


def _observe_phase_duration(phase: SandboxProvisionPhase, duration_s: float) -> None:
    try:
        _provision_phase_duration.labels(phase=phase.value).observe(duration_s)
    except Exception:
        logger.warning(
            "Failed to record sandbox provision phase metric.", exc_info=True
        )


@contextmanager
def time_provision_phase(phase: SandboxProvisionPhase) -> Generator[None]:
    """Records how long the block took, including when it raises.

    Usable as a decorator, which is how a method that owns a whole phase should
    claim it. A phase that failed still consumed the caller's time; dropping it
    would make a slow failure look free.
    """
    started_at = time.monotonic()
    try:
        yield
    finally:
        _observe_phase_duration(phase, time.monotonic() - started_at)


@contextmanager
def track_sandbox_provision_in_progress() -> Generator[None]:
    """Holds the in-flight gauge up for the duration of the block."""
    incremented = False
    try:
        _provisions_in_progress.inc()
        incremented = True
    except Exception:
        logger.warning(
            "Failed to increment sandbox provisions in-progress gauge.", exc_info=True
        )
    try:
        yield
    finally:
        if incremented:
            try:
                _provisions_in_progress.dec()
            except Exception:
                logger.warning(
                    "Failed to decrement sandbox provisions in-progress gauge.",
                    exc_info=True,
                )
