"""Validation of a proposed pairing: the same checks as creation, run on the
given config, with no report row, no background run, and no recorded outcome."""

import threading
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors import factory
from onyx.connectors.capability_checks import creation, registry, runner
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckStatus,
    CredentialCapability,
    ProposedPairingValidation,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.factory import validate_proposed_pairing
from onyx.connectors.models import InputType
from onyx.connectors.slack.config import SlackConnectorConfig
from onyx.db.credential_capability import get_capability_report_row
from onyx.db.enums import AccessType
from onyx.db.models import ConnectorCredentialPair
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_TOKEN = "fake_token"
_CHANNELS = "fake_channels"
_STORED_CONFIG: dict[str, Any] = {"channels": ["stored"]}
_PROPOSED_CONFIG: dict[str, Any] = {"channels": ["proposed"]}


class _FakeCheck(CapabilityCheck[SlackConnectorConfig]):
    config_class = SlackConnectorConfig

    def __init__(self, harness: "_Harness", check_id: str) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=f"{check_id} display",
            requires_connector_instance=False,
        )
        self._harness = harness

    def run(self, context: CapabilityCheckContext) -> None:
        self._harness.configs.append(context.connector_specific_config)
        if (release := self._harness.slow.get(self.check_id)) is not None:
            release.wait(timeout=30)
        if (error := self._harness.errors.get(self.check_id)) is not None:
            raise error


class _Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.configs: list[dict[str, Any] | None] = []
        self.errors: dict[str, Exception] = {}
        self.slow: dict[str, threading.Event] = {}
        self.send_run_task = MagicMock()
        self.record_outcome = MagicMock()
        monkeypatch.setattr(
            creation, "send_capability_check_run_task", self.send_run_task
        )
        monkeypatch.setattr(
            factory, "record_blocking_validation_outcome", self.record_outcome
        )
        for module in (creation, runner):
            monkeypatch.setattr(module, "get_capability_checks", self.checks)
        # The early return would skip validation entirely.
        monkeypatch.setattr(factory, "INTEGRATION_TESTS_MODE", False)
        monkeypatch.setattr(creation, "CREATION_BLOCKING_BUDGET_SECONDS", 1.0)

    def checks(self, source: DocumentSource) -> list[CapabilityCheck[Any]]:
        assert source == DocumentSource.SLACK
        return [_FakeCheck(self, _TOKEN), _FakeCheck(self, _CHANNELS)]

    def assert_no_side_effects(
        self, db_session: Session, cc_pair: ConnectorCredentialPair
    ) -> None:
        db_session.expire_all()
        assert (
            get_capability_report_row(
                db_session, cc_pair.credential_id, cc_pair.connector_id
            )
            is None
        )
        self.send_run_task.assert_not_called()
        self.record_outcome.assert_not_called()


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Generator[_Harness, None, None]:
    harness = _Harness(monkeypatch)
    yield harness
    # Ends the abandoned probe threads.
    for release in harness.slow.values():
        release.set()


@pytest.fixture
def slack_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK)
    cc_pair.connector.input_type = InputType.POLL
    cc_pair.connector.connector_specific_config = _STORED_CONFIG
    db_session.commit()
    yield cc_pair
    cleanup_cc_pair(db_session, cc_pair)


def _validate(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    source: DocumentSource = DocumentSource.SLACK,
) -> ProposedPairingValidation:
    return validate_proposed_pairing(
        db_session,
        connector_id=cc_pair.connector_id,
        cc_pair_id=cc_pair.id,
        source=source,
        input_type=InputType.POLL,
        connector_specific_config=_PROPOSED_CONFIG,
        credential=cc_pair.credential,
        access_type=AccessType.PUBLIC,
    )


@pytest.mark.usefixtures("tenant_context")
def test_named_checks_run_on_the_proposed_config_without_writes(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    harness.errors[_CHANNELS] = ConnectorValidationError("bot not in channel")

    result = _validate(db_session, slack_pair)

    # A failed required check is returned, not raised.
    assert result.validation_error is None
    assert {r.check_id: r.status for r in result.check_results} == {
        _TOKEN: CapabilityCheckStatus.PASSED,
        _CHANNELS: CapabilityCheckStatus.FAILED,
    }
    assert result.unfinished_check_ids == frozenset()
    assert harness.configs == [_PROPOSED_CONFIG, _PROPOSED_CONFIG]
    harness.assert_no_side_effects(db_session, slack_pair)


@pytest.mark.usefixtures("tenant_context")
def test_a_slow_check_is_unfinished_and_not_enqueued(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    harness.slow[_TOKEN] = threading.Event()

    result = _validate(db_session, slack_pair)

    assert [r.check_id for r in result.check_results] == [_CHANNELS]
    assert result.unfinished_check_ids == frozenset({_TOKEN})
    harness.assert_no_side_effects(db_session, slack_pair)


@pytest.mark.usefixtures("tenant_context")
def test_legacy_validation_error_is_returned(
    db_session: Session,
    harness: _Harness,
    slack_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "has_named_capability_checks", lambda _: False)
    connector = MagicMock()
    connector.validate_connector_settings.side_effect = ConnectorValidationError(
        "bad settings"
    )
    instantiate = MagicMock(return_value=connector)
    monkeypatch.setattr(factory, "instantiate_connector", instantiate)

    result = _validate(db_session, slack_pair)

    assert result.validation_error == "bad settings"
    assert result.check_results == []
    assert instantiate.call_args.kwargs["connector_specific_config"] == _PROPOSED_CONFIG
    assert harness.configs == []
    harness.assert_no_side_effects(db_session, slack_pair)


@pytest.mark.usefixtures("tenant_context")
def test_a_construction_error_is_returned_before_the_checks(
    db_session: Session,
    harness: _Harness,
    slack_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        factory,
        "instantiate_connector",
        MagicMock(side_effect=ValueError("blocked host")),
    )

    result = _validate(db_session, slack_pair)

    assert result.validation_error == "blocked host"
    assert harness.configs == []
    harness.assert_no_side_effects(db_session, slack_pair)


@pytest.mark.usefixtures("tenant_context")
def test_sources_without_pairing_validation_pass(
    db_session: Session, harness: _Harness, slack_pair: ConnectorCredentialPair
) -> None:
    result = _validate(db_session, slack_pair, source=DocumentSource.MOCK_CONNECTOR)

    assert result == ProposedPairingValidation()
    assert harness.configs == []
    harness.assert_no_side_effects(db_session, slack_pair)
