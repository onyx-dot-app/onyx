"""Progress of a stored run: finished checks, the running check, the queue."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from onyx.connectors.capability_checks.draft_runs import DraftCheckStateKind
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CredentialCapability,
)
from onyx.connectors.capability_checks.stored_run_progress import (
    StoredRunProgressRecorder,
    load_stored_run_progress,
)
from onyx.connectors.slack.config import SlackConnectorConfig


class _FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002
        self.values[key] = value

    def get(self, key: str) -> str | None:
        return self.values.get(key)


class _Check(CapabilityCheck[SlackConnectorConfig]):
    config_class = SlackConnectorConfig

    def __init__(self, check_id: str, *, discovery: bool = False) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=check_id,
            discovery=discovery,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        pass


def _result(check_id: str) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=CredentialCapability.INDEXING,
        check_id=check_id,
        display_name=check_id,
        required=True,
        status=CapabilityCheckStatus.PASSED,
    )


def test_progress_runs_the_first_open_check_and_queues_the_rest() -> None:
    cache = _FakeCache()
    run_id = uuid4()
    with patch(
        "onyx.connectors.capability_checks.stored_run_progress.get_cache_backend",
        return_value=cache,
    ):
        recorder = StoredRunProgressRecorder(
            run_id,
            [_Check("discover", discovery=True), _Check("auth"), _Check("scopes")],
            prior_results=[_result("kept")],
            ttl=timedelta(minutes=5),
        )
        recorder.start()
        started = load_stored_run_progress(run_id)
        assert started is not None
        # Discovery checks run last.
        assert [c.check_id for c in started.open_checks] == [
            "auth",
            "scopes",
            "discover",
        ]
        assert [c.state for c in started.open_checks] == [
            DraftCheckStateKind.RUNNING,
            DraftCheckStateKind.PENDING,
            DraftCheckStateKind.PENDING,
        ]

        recorder.on_result([_result("auth")])
        progress = load_stored_run_progress(run_id)
        assert progress is not None
        assert [r.check_id for r in progress.check_results] == ["kept", "auth"]
        assert [(c.check_id, c.state) for c in progress.open_checks] == [
            ("scopes", DraftCheckStateKind.RUNNING),
            ("discover", DraftCheckStateKind.PENDING),
        ]

        assert load_stored_run_progress(uuid4()) is None
