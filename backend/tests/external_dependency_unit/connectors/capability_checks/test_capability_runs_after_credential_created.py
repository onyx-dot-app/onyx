"""A new credential starts its source's credential-scoped named run."""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, OnyxCeleryTask
from onyx.db.credential_capability import get_capability_report_row
from onyx.db.credentials import fetch_credential_by_id
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus
from onyx.db.models import User
from onyx.server.documents import capability_check_runs
from onyx.server.documents.credential import create_credential_from_model
from onyx.server.documents.models import CredentialBase
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


@pytest.fixture
def send_task(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(capability_check_runs.client_app, "send_task", mock)
    return mock


class _CredentialCreator:
    def __init__(self, db_session: Session, admin: User) -> None:
        self._db_session = db_session
        self._admin = admin
        self.created_ids: list[int] = []

    def create(self, source: DocumentSource) -> int:
        response = create_credential_from_model(
            CredentialBase(credential_json={}, admin_public=True, source=source),
            user=self._admin,
            db_session=self._db_session,
        )
        self.created_ids.append(response.id)
        return response.id


@pytest.fixture
def creator(db_session: Session) -> Generator[_CredentialCreator, None, None]:
    admin = create_test_user(db_session, "credential_created_admin", is_admin=True)
    creator = _CredentialCreator(db_session, admin)
    yield creator
    for credential_id in creator.created_ids:
        if (
            credential := fetch_credential_by_id(credential_id, db_session)
        ) is not None:
            db_session.delete(credential)
    delete_test_user(db_session, admin)
    db_session.commit()


@pytest.mark.usefixtures("tenant_context")
def test_named_check_source_starts_a_credential_created_run(
    db_session: Session, creator: _CredentialCreator, send_task: MagicMock
) -> None:
    credential_id = creator.create(DocumentSource.SLACK)

    send_task.assert_called_once()
    assert send_task.call_args.args[0] == OnyxCeleryTask.RUN_CAPABILITY_CHECKS
    kwargs = send_task.call_args.kwargs["kwargs"]
    assert kwargs["credential_id"] == credential_id
    assert kwargs["connector_id"] is None
    assert kwargs["trigger"] == CapabilityCheckTrigger.CREDENTIAL_CREATED.value
    row = get_capability_report_row(db_session, credential_id, None)
    assert row is not None
    assert row.run_status == CapabilityReportRunStatus.RUNNING
    assert row.trigger == CapabilityCheckTrigger.CREDENTIAL_CREATED
    # The task's fence is the run id that the RUNNING mark stamped.
    assert str(row.run_id) == kwargs["run_id"]


@pytest.mark.usefixtures("tenant_context")
def test_source_without_named_checks_starts_nothing(
    db_session: Session, creator: _CredentialCreator, send_task: MagicMock
) -> None:
    credential_id = creator.create(DocumentSource.WEB)

    send_task.assert_not_called()
    assert get_capability_report_row(db_session, credential_id, None) is None


@pytest.mark.usefixtures("tenant_context")
def test_failed_enqueue_does_not_fail_credential_creation(
    db_session: Session, creator: _CredentialCreator, send_task: MagicMock
) -> None:
    send_task.side_effect = RuntimeError("broker down")

    credential_id = creator.create(DocumentSource.SLACK)

    db_session.expire_all()
    row = get_capability_report_row(db_session, credential_id, None)
    assert row is not None
    assert row.run_status == CapabilityReportRunStatus.FAILED_TO_RUN


@pytest.mark.usefixtures("tenant_context")
def test_failed_run_start_does_not_fail_credential_creation(
    db_session: Session,
    creator: _CredentialCreator,
    send_task: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capability_check_runs,
        "mark_capability_report_running",
        MagicMock(side_effect=RuntimeError("database error")),
    )

    credential_id = creator.create(DocumentSource.SLACK)

    send_task.assert_not_called()
    assert fetch_credential_by_id(credential_id, db_session) is not None
