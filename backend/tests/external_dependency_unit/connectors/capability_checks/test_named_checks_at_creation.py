"""Pairing validation for a source with named checks: what runs, what blocks,
what is stored, the blocking budget, and reuse of fresh draft-run results."""

import threading
import time
from collections.abc import Generator
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.capability_checks import (
    tasks as capability_check_tasks,
)
from onyx.background.celery.tasks.capability_checks.tasks import (
    run_capability_checks_task,
    run_draft_capability_checks_task,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors import factory
from onyx.connectors.capability_checks import creation, runner
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.factory import validate_ccpair_for_user
from onyx.connectors.models import InputType
from onyx.connectors.slack.config import SlackConnectorConfig
from onyx.db.credential_capability import (
    get_capability_report_row,
    mark_capability_report_running,
)
from onyx.db.enums import AccessType, CapabilityCheckTrigger, CapabilityReportRunStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.server.documents import capability_check_runs
from onyx.server.documents.capability_check_runs import (
    start_draft_capability_check_run,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_TOKEN = "fake_token"
_CHANNELS = "fake_channels"
_PERM_SYNC = "fake_perm_sync"


class _FakeCheck(CapabilityCheck[SlackConnectorConfig]):
    def __init__(
        self,
        harness: "_Harness",
        check_id: str,
        *,
        capability: CredentialCapability = CredentialCapability.INDEXING,
        requires_fields: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=f"{check_id} display",
            requires_connector_instance=False,
            requires_fields=requires_fields,
        )
        self._harness = harness

    def run(self, context: CapabilityCheckContext) -> None:  # noqa: ARG002
        self._harness.runs.append(self.check_id)
        if (release := self._harness.slow.get(self.check_id)) is not None:
            release.wait(timeout=30)
        if (error := self._harness.errors.get(self.check_id)) is not None:
            raise error


class _FakeConfigCheck(_FakeCheck):
    config_class = SlackConnectorConfig


class _Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.runs: list[str] = []
        self.errors: dict[str, Exception] = {}
        # A check in here waits until its event is set.
        self.slow: dict[str, threading.Event] = {}
        self.send_task = MagicMock()
        monkeypatch.setattr(
            capability_check_runs.client_app, "send_task", self.send_task
        )
        for module in (capability_check_runs, capability_check_tasks, creation, runner):
            monkeypatch.setattr(module, "get_capability_checks", self.checks)
        # The early return would skip validation entirely.
        monkeypatch.setattr(factory, "INTEGRATION_TESTS_MODE", False)
        monkeypatch.setattr(creation, "CREATION_BLOCKING_BUDGET_SECONDS", 1.0)

    def make_slow(self, check_id: str) -> threading.Event:
        release = threading.Event()
        self.slow[check_id] = release
        return release

    def release_all(self) -> None:
        for release in self.slow.values():
            release.set()

    def checks(self, source: DocumentSource) -> list[CapabilityCheck[Any]]:
        assert source == DocumentSource.SLACK
        return [
            _FakeCheck(self, _TOKEN),
            _FakeConfigCheck(self, _CHANNELS, requires_fields=frozenset({"channels"})),
            _FakeCheck(
                self, _PERM_SYNC, capability=CredentialCapability.DOC_PERMISSION_SYNC
            ),
        ]


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Generator[_Harness, None, None]:
    harness = _Harness(monkeypatch)
    yield harness
    # Ends the abandoned probe threads.
    harness.release_all()


@pytest.fixture
def slack_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK)
    cc_pair.connector.input_type = InputType.POLL
    db_session.commit()
    yield cc_pair
    cleanup_cc_pair(db_session, cc_pair)


def _validate(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    config: dict[str, Any],
    access_type: AccessType = AccessType.PUBLIC,
    enforce_creation: bool = True,
) -> bool:
    cc_pair.connector.connector_specific_config = config
    db_session.commit()
    return validate_ccpair_for_user(
        cc_pair.connector_id,
        cc_pair.credential_id,
        access_type,
        db_session,
        enforce_creation=enforce_creation,
    )


def _run_status(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> CapabilityReportRunStatus:
    db_session.expire_all()
    row = get_capability_report_row(
        db_session, cc_pair.credential_id, cc_pair.connector_id
    )
    assert row is not None
    return row.run_status


def _stored_statuses(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> dict[str, str]:
    db_session.expire_all()
    row = get_capability_report_row(
        db_session, cc_pair.credential_id, cc_pair.connector_id
    )
    assert row is not None
    assert row.trigger == CapabilityCheckTrigger.CC_PAIR_VALIDATION
    assert row.run_status == CapabilityReportRunStatus.COMPLETED
    assert row.report is not None
    return {
        result["check_id"]: result["status"] for result in row.report["check_results"]
    }


@pytest.mark.usefixtures("tenant_context")
def test_passing_checks_store_the_full_named_report(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    assert _validate(db_session, slack_pair, {"channels": ["a"]}) is True

    assert sorted(harness.runs) == sorted([_TOKEN, _CHANNELS])
    assert _stored_statuses(db_session, slack_pair) == {
        _TOKEN: "passed",
        _CHANNELS: "passed",
        _PERM_SYNC: "skipped",
    }
    harness.send_task.assert_not_called()


@pytest.mark.usefixtures("tenant_context")
def test_failed_required_check_blocks_and_is_stored(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    harness.errors[_CHANNELS] = ConnectorValidationError("bot not in channel a")

    with pytest.raises(
        ConnectorValidationError, match="fake_channels display: bot not in channel a"
    ):
        _validate(db_session, slack_pair, {"channels": ["a"]})

    assert _stored_statuses(db_session, slack_pair)[_CHANNELS] == "failed"
    assert (
        _validate(db_session, slack_pair, {"channels": ["a"]}, enforce_creation=False)
        is False
    )


@pytest.mark.usefixtures("tenant_context")
def test_indeterminate_required_check_does_not_block(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    harness.errors[_TOKEN] = UnexpectedValidationError("rate limited")

    assert _validate(db_session, slack_pair, {"channels": ["a"]}) is True

    assert _stored_statuses(db_session, slack_pair)[_TOKEN] == "indeterminate"


@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize(
    ("access_type", "perm_sync_runs"),
    [(AccessType.PRIVATE, False), (AccessType.SYNC, True)],
)
def test_perm_sync_checks_run_only_for_synced_access(
    db_session: Session,
    harness: _Harness,
    slack_pair: ConnectorCredentialPair,
    access_type: AccessType,
    perm_sync_runs: bool,
) -> None:
    _validate(db_session, slack_pair, {"channels": ["a"]}, access_type=access_type)

    assert (_PERM_SYNC in harness.runs) is perm_sync_runs


@pytest.mark.usefixtures("tenant_context")
def test_fresh_draft_results_for_the_same_form_are_reused(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    start_draft_capability_check_run(
        user_id=uuid4(),
        credential=slack_pair.credential,
        source=DocumentSource.SLACK,
        config_class=SlackConnectorConfig,
        access_type=AccessType.PUBLIC,
        draft_key=uuid4().hex,
        form_values={"channels": ["a"]},
    )
    run_draft_capability_checks_task(**harness.send_task.call_args.kwargs["kwargs"])
    assert harness.runs == [_TOKEN, _CHANNELS]
    # A reused result counts as finished at once, also for a check that would
    # now be slow.
    harness.make_slow(_CHANNELS)
    harness.send_task.reset_mock()

    started = time.monotonic()
    assert _validate(db_session, slack_pair, {"channels": ["a"]}) is True
    assert time.monotonic() - started < creation.CREATION_BLOCKING_BUDGET_SECONDS
    # Nothing ran again, and the reused results are stored.
    assert harness.runs == [_TOKEN, _CHANNELS]
    harness.send_task.assert_not_called()
    harness.release_all()
    assert _stored_statuses(db_session, slack_pair) == {
        _TOKEN: "passed",
        _CHANNELS: "passed",
        _PERM_SYNC: "skipped",
    }

    # Another form value changes only the config-reading check's key.
    assert _validate(db_session, slack_pair, {"channels": ["b"]}) is True
    assert harness.runs == [_TOKEN, _CHANNELS, _CHANNELS]


@pytest.mark.usefixtures("tenant_context")
def test_a_cached_draft_failure_runs_again_at_creation(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    # A draft run caches a failure; then the admin fixes the source.
    harness.errors[_CHANNELS] = ConnectorValidationError("bot not in channel a")
    start_draft_capability_check_run(
        user_id=uuid4(),
        credential=slack_pair.credential,
        source=DocumentSource.SLACK,
        config_class=SlackConnectorConfig,
        access_type=AccessType.PUBLIC,
        draft_key=uuid4().hex,
        form_values={"channels": ["a"]},
    )
    run_draft_capability_checks_task(**harness.send_task.call_args.kwargs["kwargs"])
    del harness.errors[_CHANNELS]
    harness.runs.clear()

    # A client without a draft run creates the pair: the failed check runs
    # again instead of reusing the cached failure, and the pair is created.
    assert _validate(db_session, slack_pair, {"channels": ["a"]}) is True
    assert harness.runs == [_CHANNELS]
    assert _stored_statuses(db_session, slack_pair)[_CHANNELS] == "passed"


@pytest.mark.usefixtures("tenant_context", "harness")
def test_validation_replaces_a_run_in_flight(
    db_session: Session, slack_pair: ConnectorCredentialPair
) -> None:
    """The validation that admits the pairing writes the report, also when
    another run holds the row."""
    held = mark_capability_report_running(
        db_session,
        credential_id=slack_pair.credential_id,
        connector_id=slack_pair.connector_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        active_within=timedelta(hours=1),
    )
    db_session.commit()
    assert held is not None

    assert _validate(db_session, slack_pair, {"channels": ["a"]}) is True

    assert _stored_statuses(db_session, slack_pair)[_CHANNELS] == "passed"


@pytest.mark.usefixtures("tenant_context", "harness")
def test_failed_report_write_retires_the_running_mark(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        creation,
        "upsert_completed_capability_report",
        MagicMock(side_effect=RuntimeError("database error")),
    )

    with pytest.raises(RuntimeError, match="database error"):
        _validate(db_session, slack_pair, {"channels": ["a"]})

    db_session.expire_all()
    row = get_capability_report_row(
        db_session, slack_pair.credential_id, slack_pair.connector_id
    )
    assert row is not None
    assert row.run_status == CapabilityReportRunStatus.FAILED_TO_RUN


@pytest.mark.usefixtures("tenant_context")
def test_fast_required_failure_blocks_while_another_check_is_slow(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    harness.make_slow(_TOKEN)
    harness.errors[_CHANNELS] = ConnectorValidationError("bot not in channel a")

    with pytest.raises(ConnectorValidationError, match="bot not in channel a"):
        _validate(db_session, slack_pair, {"channels": ["a"]})

    # The rejection stores the report; no background run starts.
    statuses = _stored_statuses(db_session, slack_pair)
    assert statuses[_CHANNELS] == "failed"
    assert statuses[_TOKEN] == "indeterminate"
    harness.send_task.assert_not_called()


@pytest.mark.usefixtures("tenant_context")
def test_slow_required_check_does_not_block_and_its_result_lands_later(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    release = harness.make_slow(_TOKEN)
    harness.errors[_TOKEN] = ConnectorValidationError("token revoked")

    started = time.monotonic()
    assert _validate(db_session, slack_pair, {"channels": ["a"]}) is True
    assert time.monotonic() - started < creation.CREATION_BLOCKING_BUDGET_SECONDS + 1

    # The row stays RUNNING until the background run stores the full report.
    assert _run_status(db_session, slack_pair) == CapabilityReportRunStatus.RUNNING
    harness.send_task.assert_called_once()
    send_kwargs = harness.send_task.call_args.kwargs
    assert send_kwargs["expires"] > 0
    task_kwargs = send_kwargs["kwargs"]
    assert task_kwargs["check_ids"] == [_TOKEN]
    assert task_kwargs["access_type"] == AccessType.PUBLIC.value

    release.set()
    run_capability_checks_task(**task_kwargs)

    assert _stored_statuses(db_session, slack_pair) == {
        _TOKEN: "failed",
        _CHANNELS: "passed",
        _PERM_SYNC: "skipped",
    }
    # The background run ran only the unfinished check.
    assert sorted(harness.runs) == sorted([_TOKEN, _TOKEN, _CHANNELS])


@pytest.mark.usefixtures("tenant_context")
def test_failed_enqueue_marks_the_run_failed_to_run(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    harness.make_slow(_TOKEN)
    harness.send_task.side_effect = RuntimeError("broker down")

    # Creation still succeeds; the dead run is for the admin to re-run.
    assert _validate(db_session, slack_pair, {"channels": ["a"]}) is True

    assert (
        _run_status(db_session, slack_pair) == CapabilityReportRunStatus.FAILED_TO_RUN
    )
