"""A failed creation validation must remove the connector row the create call
already committed, or the name stays taken for the retry."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.db.enums import AccessType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import cc_pair as cc_pair_server
from onyx.server.documents import connector as connector_server
from onyx.server.documents.models import (
    ConnectorCredentialPairMetadata,
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


def _session_that_propagates() -> MagicMock:
    """A MagicMock's ``with session.begin()`` swallows exceptions, a real one
    does not."""
    db_session = MagicMock()
    db_session.begin.return_value.__exit__.return_value = False
    return db_session


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
        "discard_connector_if_unpaired": MagicMock(return_value=True),
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
    stubbed_creation["discard_connector_if_unpaired"].assert_called_once_with(
        db_session, 7
    )
    stubbed_creation["delete_credential"].assert_called_once_with(9, db_session)


def test_duplicate_name_removes_nothing(
    request_data: ConnectorUpdateRequest, stubbed_creation: dict[str, MagicMock]
) -> None:
    stubbed_creation["create_connector"].side_effect = ValueError(
        "Connector by this name already exists, duplicate naming not allowed."
    )

    with pytest.raises(HTTPException) as raised:
        connector_server.create_connector_with_mock_credential(
            connector_data=request_data, user=MagicMock(), db_session=MagicMock()
        )

    assert raised.value.status_code == 400
    stubbed_creation["discard_connector_if_unpaired"].assert_not_called()
    stubbed_creation["delete_credential"].assert_not_called()


def test_connector_paired_meanwhile_keeps_the_credential(
    request_data: ConnectorUpdateRequest, stubbed_creation: dict[str, MagicMock]
) -> None:
    stubbed_creation["discard_connector_if_unpaired"].return_value = False

    with pytest.raises(HTTPException):
        connector_server.create_connector_with_mock_credential(
            connector_data=request_data, user=MagicMock(), db_session=MagicMock()
        )

    stubbed_creation["delete_credential"].assert_not_called()


@pytest.fixture
def stubbed_association(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    stubs = {
        "assert_within_scope": MagicMock(),
        "get_cc_pair_ids_for_connector": MagicMock(return_value=set()),
        "fetch_credential_by_id_for_user": MagicMock(return_value=MagicMock()),
        "validate_ccpair_for_user": MagicMock(
            side_effect=ConnectorValidationError("no access to graph api")
        ),
        "add_credential_to_connector": MagicMock(),
        "discard_connector_if_unpaired": MagicMock(return_value=True),
    }
    for name, stub in stubs.items():
        monkeypatch.setattr(cc_pair_server, name, stub)
    return stubs


def test_failed_link_removes_the_unpaired_connector(
    stubbed_association: dict[str, MagicMock],
) -> None:
    db_session = _session_that_propagates()

    with pytest.raises(OnyxError) as raised:
        cc_pair_server.associate_credential_to_connector(
            connector_id=7,
            credential_id=9,
            metadata=ConnectorCredentialPairMetadata(
                name="sharepoint-retry", access_type=AccessType.PUBLIC
            ),
            user=MagicMock(),
            db_session=db_session,
            tenant_id="public",
        )

    assert raised.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert "no access to graph api" in raised.value.detail
    assert "removed" in raised.value.detail
    stubbed_association["discard_connector_if_unpaired"].assert_called_once_with(
        db_session, 7
    )
    stubbed_association["add_credential_to_connector"].assert_not_called()


def test_failed_link_keeps_a_connector_paired_meanwhile(
    stubbed_association: dict[str, MagicMock],
) -> None:
    stubbed_association["discard_connector_if_unpaired"].return_value = False

    with pytest.raises(OnyxError) as raised:
        cc_pair_server.associate_credential_to_connector(
            connector_id=7,
            credential_id=9,
            metadata=ConnectorCredentialPairMetadata(
                name="sharepoint-retry", access_type=AccessType.PUBLIC
            ),
            user=MagicMock(),
            db_session=_session_that_propagates(),
            tenant_id="public",
        )

    assert "removed" not in raised.value.detail


def test_credential_cleanup_failure_keeps_the_validation_error(
    request_data: ConnectorUpdateRequest, stubbed_creation: dict[str, MagicMock]
) -> None:
    stubbed_creation["delete_credential"].side_effect = RuntimeError("db down")
    db_session = MagicMock()

    with pytest.raises(HTTPException) as raised:
        connector_server.create_connector_with_mock_credential(
            connector_data=request_data, user=MagicMock(), db_session=db_session
        )

    assert "no access to graph api" in raised.value.detail
    assert db_session.rollback.call_count == 2
