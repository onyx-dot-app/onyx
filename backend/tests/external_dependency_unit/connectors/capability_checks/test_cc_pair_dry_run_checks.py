"""Dry runs of the capability checks for a proposed state of an existing
cc-pair: they use the proposed state and the pair's connector, write no report
row, cache apart from create-form runs and other pairs, and their results are
reused by the edit's validations. Also covers the CONNECTOR_CONFIG_UPDATE
trigger, which runs the named checks as pairing validation does."""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.capability_checks import (
    tasks as capability_check_tasks,
)
from onyx.background.celery.tasks.capability_checks.tasks import (
    run_draft_capability_checks_task,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors import factory
from onyx.connectors.capability_checks import creation, runner
from onyx.connectors.capability_checks.creation import get_cc_pair_dry_run_results
from onyx.connectors.capability_checks.draft_runs import (
    DraftCheckRunSnapshot,
    DraftCheckStateKind,
    DraftRunStatus,
    read_draft_run_for_user,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckStatus,
    CredentialCapability,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.factory import validate_ccpair_for_user, validate_proposed_pairing
from onyx.connectors.models import InputType
from onyx.connectors.slack.config import SlackConnectorConfig
from onyx.db.credential_capability import get_capability_report_row
from onyx.db.enums import AccessType, CapabilityCheckTrigger, CapabilityReportRunStatus
from onyx.db.models import ConnectorCredentialPair, Credential
from onyx.server.documents import capability_check_runs
from onyx.server.documents.capability_check_runs import (
    start_cc_pair_draft_check_run,
    start_draft_capability_check_run,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_TOKEN = "fake_token"
_CHANNELS = "fake_channels"
_STORED_CONFIG: dict[str, Any] = {"channels": ["stored"]}
_PROPOSED_CONFIG: dict[str, Any] = {"channels": ["proposed"]}


class _FakeCheck(CapabilityCheck[SlackConnectorConfig]):
    def __init__(self, harness: "_Harness", check_id: str) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=f"{check_id} display",
            requires_connector_instance=False,
        )
        self._harness = harness

    def run(self, context: CapabilityCheckContext) -> None:
        self._harness.runs.append(self.check_id)
        self._harness.configs.append(context.connector_specific_config)
        if (error := self._harness.errors.get(self.check_id)) is not None:
            raise error


class _FakeConfigCheck(_FakeCheck):
    config_class = SlackConnectorConfig


class _Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.runs: list[str] = []
        self.configs: list[dict[str, Any] | None] = []
        self.errors: dict[str, Exception] = {}
        self.send_task = MagicMock()
        self.send_run_task = MagicMock()
        monkeypatch.setattr(
            capability_check_runs.client_app, "send_task", self.send_task
        )
        monkeypatch.setattr(
            creation, "send_capability_check_run_task", self.send_run_task
        )
        for module in (capability_check_runs, capability_check_tasks, creation, runner):
            monkeypatch.setattr(module, "get_capability_checks", self.checks)
        # The early return would skip validation entirely.
        monkeypatch.setattr(factory, "INTEGRATION_TESTS_MODE", False)
        monkeypatch.setattr(creation, "CREATION_BLOCKING_BUDGET_SECONDS", 5.0)
        self.report_kwargs: list[dict[str, Any]] = []
        generate = capability_check_tasks.generate_capability_report

        def recording_generate(*args: Any, **kwargs: Any) -> Any:
            self.report_kwargs.append(kwargs)
            return generate(*args, **kwargs)

        monkeypatch.setattr(
            capability_check_tasks, "generate_capability_report", recording_generate
        )

    def checks(self, source: DocumentSource) -> list[CapabilityCheck[Any]]:
        assert source == DocumentSource.SLACK
        return [_FakeCheck(self, _TOKEN), _FakeConfigCheck(self, _CHANNELS)]

    def run_last_task(self) -> None:
        run_draft_capability_checks_task(**self.send_task.call_args.kwargs["kwargs"])


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    return _Harness(monkeypatch)


def _slack_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK)
    cc_pair.connector.input_type = InputType.POLL
    cc_pair.connector.connector_specific_config = _STORED_CONFIG
    db_session.commit()
    yield cc_pair
    cleanup_cc_pair(db_session, cc_pair)


@pytest.fixture
def slack_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    yield from _slack_pair(db_session)


@pytest.fixture
def other_slack_pair(
    db_session: Session,
) -> Generator[ConnectorCredentialPair, None, None]:
    yield from _slack_pair(db_session)


def _dry_run(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    user_id: UUID,
    credential: Credential | None = None,
    config: dict[str, Any] = _PROPOSED_CONFIG,
) -> DraftCheckRunSnapshot:
    return start_cc_pair_draft_check_run(
        db_session,
        user_id=user_id,
        cc_pair_id=cc_pair.id,
        proposed_credential=credential,
        access_type=AccessType.PUBLIC,
        connector_specific_config=config,
    )


def _states(snapshot: DraftCheckRunSnapshot) -> dict[str, DraftCheckStateKind]:
    return {check.check_id: check.state for check in snapshot.checks}


@pytest.mark.usefixtures("tenant_context")
def test_dry_run_uses_the_proposed_state_and_the_pairs_connector(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    user_id = uuid4()
    started = _dry_run(db_session, slack_pair, user_id)
    assert started.status == DraftRunStatus.RUNNING
    harness.run_last_task()

    # The proposed config reaches the checks, never the stored one.
    assert harness.configs == [_PROPOSED_CONFIG, _PROPOSED_CONFIG]
    assert harness.report_kwargs[-1]["connector_id"] == slack_pair.connector_id
    assert harness.report_kwargs[-1]["input_type"] == InputType.POLL
    snapshot = read_draft_run_for_user(started.run_id, user_id)
    assert snapshot is not None
    assert snapshot.status == DraftRunStatus.COMPLETED
    assert _states(snapshot) == {
        _TOKEN: DraftCheckStateKind.PASSED,
        _CHANNELS: DraftCheckStateKind.PASSED,
    }
    # A dry run writes no report row.
    db_session.expire_all()
    assert (
        get_capability_report_row(
            db_session, slack_pair.credential_id, slack_pair.connector_id
        )
        is None
    )


@pytest.mark.usefixtures("tenant_context")
def test_dry_run_of_an_all_default_config_runs_the_config_checks(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    # {} is a complete Slack config: every field takes its default.
    user_id = uuid4()
    started = _dry_run(db_session, slack_pair, user_id, config={})
    assert _states(started) == {
        _TOKEN: DraftCheckStateKind.PENDING,
        _CHANNELS: DraftCheckStateKind.PENDING,
    }
    harness.run_last_task()

    assert harness.configs == [{}, {}]
    snapshot = read_draft_run_for_user(started.run_id, user_id)
    assert snapshot is not None
    assert _states(snapshot) == {
        _TOKEN: DraftCheckStateKind.PASSED,
        _CHANNELS: DraftCheckStateKind.PASSED,
    }


@pytest.mark.usefixtures("tenant_context")
def test_dry_run_results_are_cached_apart_from_create_forms_and_other_pairs(
    db_session: Session,
    harness: _Harness,
    slack_pair: ConnectorCredentialPair,
    other_slack_pair: ConnectorCredentialPair,
) -> None:
    user_id = uuid4()
    # A create-form draft run with the same credential, access type and form.
    start_draft_capability_check_run(
        user_id=user_id,
        credential=slack_pair.credential,
        source=DocumentSource.SLACK,
        config_class=SlackConnectorConfig,
        access_type=AccessType.PUBLIC,
        draft_key=uuid4().hex,
        form_values=_PROPOSED_CONFIG,
    )
    harness.run_last_task()
    assert harness.runs == [_TOKEN, _CHANNELS]

    # The pair's dry run does not reuse the create-form results.
    harness.send_task.reset_mock()
    _dry_run(db_session, slack_pair, user_id)
    harness.run_last_task()
    assert harness.runs == [_TOKEN, _CHANNELS] * 2

    # Another pair with the same proposed credential does not reuse them.
    harness.send_task.reset_mock()
    _dry_run(db_session, other_slack_pair, user_id, credential=slack_pair.credential)
    harness.run_last_task()
    assert harness.runs == [_TOKEN, _CHANNELS] * 3

    # The same pair and proposed state reuses its own results.
    harness.send_task.reset_mock()
    cached = _dry_run(db_session, slack_pair, user_id)
    assert cached.status == DraftRunStatus.COMPLETED
    assert all(check.from_cache for check in cached.checks)
    harness.send_task.assert_not_called()


@pytest.mark.usefixtures("tenant_context")
def test_a_newer_dry_run_of_the_pair_supersedes_the_earlier(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    user_id = uuid4()
    first = _dry_run(db_session, slack_pair, user_id)
    first_task_kwargs = harness.send_task.call_args.kwargs["kwargs"]
    second = _dry_run(db_session, slack_pair, user_id)

    first_read = read_draft_run_for_user(first.run_id, user_id)
    assert first_read is not None
    assert first_read.status == DraftRunStatus.SUPERSEDED
    # The superseded task stops before it runs a check.
    run_draft_capability_checks_task(**first_task_kwargs)
    assert harness.runs == []

    harness.run_last_task()
    second_read = read_draft_run_for_user(second.run_id, user_id)
    assert second_read is not None
    assert second_read.status == DraftRunStatus.COMPLETED


@pytest.mark.usefixtures("tenant_context")
def test_edit_validations_read_the_pairs_dry_run_results(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    harness.errors[_CHANNELS] = ConnectorValidationError("bot not in channel")
    _dry_run(db_session, slack_pair, uuid4())
    harness.run_last_task()
    harness.runs.clear()

    results = get_cc_pair_dry_run_results(
        cc_pair_id=slack_pair.id,
        credential=slack_pair.credential,
        source=DocumentSource.SLACK,
        access_type=AccessType.PUBLIC,
        connector_specific_config=_PROPOSED_CONFIG,
    )
    assert {result.check_id: result.status for result in results} == {
        _TOKEN: CapabilityCheckStatus.PASSED,
        _CHANNELS: CapabilityCheckStatus.FAILED,
    }

    # The plan's validation reuses the passed result and runs the failed check
    # again.
    del harness.errors[_CHANNELS]
    validation = validate_proposed_pairing(
        db_session,
        connector_id=slack_pair.connector_id,
        cc_pair_id=slack_pair.id,
        source=DocumentSource.SLACK,
        input_type=InputType.POLL,
        connector_specific_config=_PROPOSED_CONFIG,
        credential=slack_pair.credential,
        access_type=AccessType.PUBLIC,
    )
    assert harness.runs == [_CHANNELS]
    assert {result.check_id: result.status for result in validation.check_results} == {
        _TOKEN: CapabilityCheckStatus.PASSED,
        _CHANNELS: CapabilityCheckStatus.PASSED,
    }


@pytest.mark.usefixtures("tenant_context")
def test_connector_config_update_runs_the_named_checks(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    # Apply writes the proposed state before the validation reads it.
    slack_pair.connector.connector_specific_config = _PROPOSED_CONFIG
    db_session.commit()
    _dry_run(db_session, slack_pair, uuid4())
    harness.run_last_task()
    harness.runs.clear()

    assert (
        validate_ccpair_for_user(
            slack_pair.connector_id,
            slack_pair.credential_id,
            AccessType.PUBLIC,
            db_session,
            trigger=CapabilityCheckTrigger.CONNECTOR_CONFIG_UPDATE,
        )
        is True
    )

    # The dry run's results are reused, and the report keeps the trigger.
    assert harness.runs == []
    db_session.expire_all()
    row = get_capability_report_row(
        db_session, slack_pair.credential_id, slack_pair.connector_id
    )
    assert row is not None
    assert row.trigger == CapabilityCheckTrigger.CONNECTOR_CONFIG_UPDATE
    assert row.run_status == CapabilityReportRunStatus.COMPLETED
    assert row.report is not None
    assert {
        result["check_id"]: result["status"] for result in row.report["check_results"]
    } == {_TOKEN: "passed", _CHANNELS: "passed"}

    # A failed required check blocks the edit, as it blocks a pairing.
    harness.errors[_CHANNELS] = ConnectorValidationError("bot not in channel")
    slack_pair.connector.connector_specific_config = {"channels": ["other"]}
    db_session.commit()
    with pytest.raises(ConnectorValidationError, match="bot not in channel"):
        validate_ccpair_for_user(
            slack_pair.connector_id,
            slack_pair.credential_id,
            AccessType.PUBLIC,
            db_session,
            trigger=CapabilityCheckTrigger.CONNECTOR_CONFIG_UPDATE,
        )
