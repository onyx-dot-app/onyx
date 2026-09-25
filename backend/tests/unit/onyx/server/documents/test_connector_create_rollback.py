"""A failed validation in the mock-credential create flow must remove the
connector and credential rows it already committed, or the name stays taken."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.db.enums import AccessType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import connector as connector_server
from onyx.server.documents.models import (
    ConnectorUpdateRequest,
    DocumentSource,
    InputType,
    ObjectCreationIdResponse,
)


@pytest.fixture
def request_data() -> ConnectorUpdateRequest:
    return ConnectorUpdateRequest(
        name="sharepoint-retry",
        source=DocumentSource.SHAREPOINT,
        input_type=InputType.POLL,
        connector_specific_config={"sites": []},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
        access_type=AccessType.PUBLIC,
        groups=[],
    )


@pytest.fixture
def stubbed_creation(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    stubs = {
        "assert_within_scope": MagicMock(),
        "create_connector": MagicMock(return_value=ObjectCreationIdResponse(id=7)),
        "create_credential": MagicMock(return_value=MagicMock(id=9)),
        "validate_ccpair_for_user": MagicMock(
            side_effect=ConnectorValidationError("no access to graph api")
        ),
        "delete_credential": MagicMock(),
        "delete_connector": MagicMock(),
        "lock_connector_for_delete": MagicMock(return_value=(MagicMock(), set())),
        "emit_audit_event": MagicMock(),
        "actor_from_user": MagicMock(),
    }
    for name, stub in stubs.items():
        monkeypatch.setattr(connector_server, name, stub)
    return stubs


def test_failed_validation_removes_both_rows(
    request_data: ConnectorUpdateRequest, stubbed_creation: dict[str, MagicMock]
) -> None:
    db_session = MagicMock()

    with pytest.raises(HTTPException) as raised:
        connector_server.create_connector_with_mock_credential(
            connector_data=request_data, user=MagicMock(), db_session=db_session
        )

    assert raised.value.status_code == 400
    assert "no access to graph api" in raised.value.detail
    stubbed_creation["delete_credential"].assert_called_once_with(9, db_session)
    stubbed_creation["delete_connector"].assert_called_once_with(db_session, 7)
    db_session.begin.assert_called_once()


def test_duplicate_name_removes_nothing(
    request_data: ConnectorUpdateRequest, stubbed_creation: dict[str, MagicMock]
) -> None:
    stubbed_creation["create_connector"].side_effect = ValueError(
        "Connector by this name already exists, duplicate naming not allowed."
    )
    db_session = MagicMock()

    with pytest.raises(HTTPException) as raised:
        connector_server.create_connector_with_mock_credential(
            connector_data=request_data, user=MagicMock(), db_session=db_session
        )

    assert raised.value.status_code == 400
    stubbed_creation["delete_credential"].assert_not_called()
    stubbed_creation["delete_connector"].assert_not_called()


def test_connector_paired_meanwhile_keeps_both_rows(
    request_data: ConnectorUpdateRequest, stubbed_creation: dict[str, MagicMock]
) -> None:
    stubbed_creation["lock_connector_for_delete"].return_value = (MagicMock(), {5})
    db_session = MagicMock()

    with pytest.raises(HTTPException):
        connector_server.create_connector_with_mock_credential(
            connector_data=request_data, user=MagicMock(), db_session=db_session
        )

    stubbed_creation["delete_credential"].assert_not_called()
    stubbed_creation["delete_connector"].assert_not_called()


def _session_that_propagates() -> MagicMock:
    """A MagicMock's ``with session.begin()`` swallows exceptions, a real one
    does not."""
    db_session = MagicMock()
    db_session.begin.return_value.__exit__.return_value = False
    return db_session


def test_delete_removes_an_unpaired_connector(
    stubbed_creation: dict[str, MagicMock],
) -> None:
    db_session = MagicMock()

    connector_server.delete_connector_by_id(
        connector_id=7, user=MagicMock(), db_session=db_session
    )

    stubbed_creation["delete_connector"].assert_called_once_with(
        db_session=db_session, connector_id=7
    )


def test_only_unpaired_refuses_a_paired_connector(
    stubbed_creation: dict[str, MagicMock],
) -> None:
    stubbed_creation["lock_connector_for_delete"].return_value = (MagicMock(), {5})
    db_session = _session_that_propagates()

    with pytest.raises(OnyxError) as raised:
        connector_server.delete_connector_by_id(
            connector_id=7, only_unpaired=True, user=MagicMock(), db_session=db_session
        )

    assert raised.value.error_code == OnyxErrorCode.CONFLICT
    stubbed_creation["delete_connector"].assert_not_called()
