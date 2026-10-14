"""A failed validation in the mock-credential create flow must remove the
connector and credential rows it already committed, or the name stays taken."""

from unittest.mock import MagicMock

import pytest

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    UnexpectedValidationError,
)
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
        "discard_credential_if_unpaired": MagicMock(),
        "discard_connector_if_unpaired": MagicMock(return_value=True),
    }
    for name, stub in stubs.items():
        monkeypatch.setattr(connector_server, name, stub)
    return stubs


def test_failed_validation_removes_both_rows(
    request_data: ConnectorUpdateRequest, stubbed_creation: dict[str, MagicMock]
) -> None:
    db_session = MagicMock()

    with pytest.raises(OnyxError) as raised:
        connector_server.create_connector_with_mock_credential(
            connector_data=request_data, user=MagicMock(), db_session=db_session
        )

    assert raised.value.error_code == OnyxErrorCode.CONNECTOR_VALIDATION_FAILED
    assert "no access to graph api" in raised.value.detail
    stubbed_creation["discard_connector_if_unpaired"].assert_called_once_with(
        db_session, 7
    )
    stubbed_creation["discard_credential_if_unpaired"].assert_called_once_with(
        db_session, 9
    )


def test_duplicate_name_removes_nothing(
    request_data: ConnectorUpdateRequest, stubbed_creation: dict[str, MagicMock]
) -> None:
    stubbed_creation["create_connector"].side_effect = ValueError(
        "Connector by this name already exists, duplicate naming not allowed."
    )

    with pytest.raises(OnyxError) as raised:
        connector_server.create_connector_with_mock_credential(
            connector_data=request_data, user=MagicMock(), db_session=MagicMock()
        )

    assert raised.value.error_code == OnyxErrorCode.INVALID_INPUT
    stubbed_creation["discard_connector_if_unpaired"].assert_not_called()
    stubbed_creation["discard_credential_if_unpaired"].assert_not_called()


def test_connector_paired_meanwhile_still_drops_the_mock_credential(
    request_data: ConnectorUpdateRequest, stubbed_creation: dict[str, MagicMock]
) -> None:
    stubbed_creation["discard_connector_if_unpaired"].return_value = False
    db_session = MagicMock()

    with pytest.raises(OnyxError):
        connector_server.create_connector_with_mock_credential(
            connector_data=request_data, user=MagicMock(), db_session=db_session
        )

    stubbed_creation["discard_credential_if_unpaired"].assert_called_once_with(
        db_session, 9
    )


def test_transient_validation_failure_also_frees_the_name(
    request_data: ConnectorUpdateRequest, stubbed_creation: dict[str, MagicMock]
) -> None:
    stubbed_creation[
        "validate_ccpair_for_user"
    ].side_effect = UnexpectedValidationError("source unreachable")
    db_session = MagicMock()

    with pytest.raises(OnyxError) as raised:
        connector_server.create_connector_with_mock_credential(
            connector_data=request_data, user=MagicMock(), db_session=db_session
        )

    assert raised.value.error_code == OnyxErrorCode.CONNECTOR_VALIDATION_FAILED
    stubbed_creation["discard_connector_if_unpaired"].assert_called_once_with(
        db_session, 7
    )
