"""A new or swapped pairing starts the source's full named capability run."""

from collections.abc import Generator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, OnyxCeleryTask
from onyx.db.connector_credential_pair import get_connector_credential_pair
from onyx.db.credential_capability import get_capability_report_row
from onyx.db.enums import (
    AccessType,
    CapabilityCheckTrigger,
    CapabilityReportRunStatus,
)
from onyx.db.models import ConnectorCredentialPair, Credential
from onyx.server.documents import capability_check_runs
from onyx.server.documents import cc_pair as cc_pair_api
from onyx.server.documents import credential as credential_api
from onyx.server.documents.capability_check_runs import (
    start_capability_checks_for_new_pairing,
)
from onyx.server.documents.cc_pair import associate_credential_to_connector
from onyx.server.documents.credential import swap_credentials_for_connector
from onyx.server.documents.models import (
    ConnectorCredentialPairMetadata,
    CredentialSwapRequest,
)
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def send_task(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(capability_check_runs.client_app, "send_task", mock)
    return mock


def _pair(
    db_session: Session, source: DocumentSource
) -> Generator[ConnectorCredentialPair, None, None]:
    cc_pair = make_cc_pair(db_session, source=source)
    yield cc_pair
    cleanup_cc_pair(db_session, cc_pair)


@pytest.fixture
def slack_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    yield from _pair(db_session, DocumentSource.SLACK)


@pytest.fixture
def web_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    yield from _pair(db_session, DocumentSource.WEB)


def _start(db_session: Session, cc_pair: ConnectorCredentialPair) -> None:
    start_capability_checks_for_new_pairing(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
    )


@pytest.mark.usefixtures("tenant_context")
def test_named_check_source_starts_the_full_run(
    db_session: Session, slack_pair: ConnectorCredentialPair, send_task: MagicMock
) -> None:
    _start(db_session, slack_pair)

    send_task.assert_called_once()
    assert send_task.call_args.args[0] == OnyxCeleryTask.RUN_CAPABILITY_CHECKS
    kwargs = send_task.call_args.kwargs["kwargs"]
    assert kwargs["connector_id"] == slack_pair.connector_id
    assert kwargs["trigger"] == CapabilityCheckTrigger.CC_PAIR_VALIDATION.value
    row = get_capability_report_row(
        db_session, slack_pair.credential_id, slack_pair.connector_id
    )
    assert row is not None
    assert row.run_status == CapabilityReportRunStatus.RUNNING
    assert row.trigger == CapabilityCheckTrigger.CC_PAIR_VALIDATION
    # The task's fence is the run id that the RUNNING mark stamped.
    assert str(row.run_id) == kwargs["run_id"]


@pytest.mark.usefixtures("tenant_context")
def test_source_without_named_checks_starts_nothing(
    db_session: Session, web_pair: ConnectorCredentialPair, send_task: MagicMock
) -> None:
    _start(db_session, web_pair)

    send_task.assert_not_called()
    assert (
        get_capability_report_row(
            db_session, web_pair.credential_id, web_pair.connector_id
        )
        is None
    )


@pytest.mark.usefixtures("tenant_context")
def test_failed_enqueue_marks_the_run_failed_without_raising(
    db_session: Session, slack_pair: ConnectorCredentialPair, send_task: MagicMock
) -> None:
    send_task.side_effect = RuntimeError("broker down")

    _start(db_session, slack_pair)

    db_session.expire_all()
    row = get_capability_report_row(
        db_session, slack_pair.credential_id, slack_pair.connector_id
    )
    assert row is not None
    assert row.run_status == CapabilityReportRunStatus.FAILED_TO_RUN


def _fail_the_running_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("database error")

    monkeypatch.setattr(capability_check_runs, "mark_capability_report_running", _raise)


@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize("run_start_fails", [False, True])
def test_association_starts_the_run_and_still_triggers_indexing(
    db_session: Session,
    send_task: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    run_start_fails: bool,
) -> None:
    """The association route starts the run, and a failed start does not change
    the pairing result or skip the indexing trigger."""
    admin = create_test_user(db_session, "cap-assoc", is_admin=True)
    unpaired = make_cc_pair(db_session, source=DocumentSource.SLACK)
    connector_id = unpaired.connector_id
    credential_id = unpaired.credential_id
    db_session.delete(unpaired)
    db_session.commit()
    monkeypatch.setattr(cc_pair_api, "validate_ccpair_for_user", MagicMock())
    if run_start_fails:
        _fail_the_running_mark(monkeypatch)

    try:
        response = associate_credential_to_connector(
            connector_id,
            credential_id,
            ConnectorCredentialPairMetadata(
                name=f"cap-assoc-{uuid4().hex[:8]}", access_type=AccessType.PUBLIC
            ),
            admin,
            db_session,
            get_current_tenant_id(),
        )

        assert response.success
        sent_tasks = [call.args[0] for call in send_task.call_args_list]
        assert OnyxCeleryTask.CHECK_FOR_INDEXING in sent_tasks
        assert (OnyxCeleryTask.RUN_CAPABILITY_CHECKS in sent_tasks) is not (
            run_start_fails
        )
    finally:
        db_session.rollback()
        pair = get_connector_credential_pair(db_session, connector_id, credential_id)
        if pair is not None:
            cleanup_cc_pair(db_session, pair)


@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize("run_start_fails", [False, True])
def test_credential_swap_starts_the_run_and_still_succeeds(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    send_task: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    run_start_fails: bool,
) -> None:
    admin = create_test_user(db_session, "cap-swap", is_admin=True)
    old_credential_id = slack_pair.credential_id
    new_credential = Credential(source=DocumentSource.SLACK, credential_json={})
    db_session.add(new_credential)
    db_session.commit()
    monkeypatch.setattr(credential_api, "validate_ccpair_for_user", MagicMock())
    if run_start_fails:
        _fail_the_running_mark(monkeypatch)

    try:
        response = swap_credentials_for_connector(
            CredentialSwapRequest(
                new_credential_id=new_credential.id,
                connector_id=slack_pair.connector_id,
                access_type=AccessType.PUBLIC,
            ),
            admin,
            db_session,
        )

        assert response.success
        sent_tasks = [call.args[0] for call in send_task.call_args_list]
        assert (OnyxCeleryTask.RUN_CAPABILITY_CHECKS in sent_tasks) is not (
            run_start_fails
        )
    finally:
        db_session.rollback()
        old_credential = db_session.get(Credential, old_credential_id)
        if old_credential is not None:
            db_session.delete(old_credential)
            db_session.commit()
