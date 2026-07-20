from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.seafile.libraries import SeafileLibraryListingError
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import connector as connector_api
from onyx.server.documents.connector import list_seafile_libraries
from onyx.server.documents.connector import SeafileLibrariesRequest


def test_route_rejects_missing_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        connector_api, "fetch_credential_by_id_for_user", Mock(return_value=None)
    )

    with pytest.raises(OnyxError) as exc_info:
        list_seafile_libraries(
            SeafileLibrariesRequest(
                base_url="https://seafile.example.com",
                credential_id=123,
            ),
            user=cast(User, SimpleNamespace()),
            db_session=cast(Session, SimpleNamespace()),
        )

    assert exc_info.value.error_code == OnyxErrorCode.CREDENTIAL_NOT_FOUND


def test_route_rejects_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    credential_json = Mock()
    credential_json.get_value.return_value = {}
    credential = SimpleNamespace(
        source=DocumentSource.SEAFILE,
        credential_json=credential_json,
    )
    monkeypatch.setattr(
        connector_api, "fetch_credential_by_id_for_user", Mock(return_value=credential)
    )

    with pytest.raises(OnyxError) as exc_info:
        list_seafile_libraries(
            SeafileLibrariesRequest(
                base_url="https://seafile.example.com",
                credential_id=123,
            ),
            user=cast(User, SimpleNamespace()),
            db_session=cast(Session, SimpleNamespace()),
        )

    assert exc_info.value.error_code == OnyxErrorCode.CREDENTIAL_INVALID


@pytest.mark.parametrize(
    ("connector_exception", "error_code"),
    [
        (
            ConnectorValidationError("bad base url"),
            OnyxErrorCode.VALIDATION_ERROR,
        ),
        (
            CredentialExpiredError("expired"),
            OnyxErrorCode.CREDENTIAL_EXPIRED,
        ),
        (
            InsufficientPermissionsError("forbidden"),
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        ),
        (
            SeafileLibraryListingError("upstream"),
            OnyxErrorCode.BAD_GATEWAY,
        ),
    ],
)
def test_route_maps_connector_library_errors(
    monkeypatch: pytest.MonkeyPatch,
    connector_exception: Exception,
    error_code: OnyxErrorCode,
) -> None:
    credential_json = Mock()
    credential_json.get_value.return_value = {"seafile_api_token": "token"}
    credential = SimpleNamespace(
        source=DocumentSource.SEAFILE,
        credential_json=credential_json,
    )
    monkeypatch.setattr(
        connector_api, "fetch_credential_by_id_for_user", Mock(return_value=credential)
    )
    monkeypatch.setattr(
        connector_api,
        "list_libraries_from_seafile",
        Mock(side_effect=connector_exception),
    )

    with pytest.raises(OnyxError) as exc_info:
        list_seafile_libraries(
            SeafileLibrariesRequest(
                base_url="https://seafile.example.com",
                credential_id=123,
            ),
            user=cast(User, SimpleNamespace()),
            db_session=cast(Session, SimpleNamespace()),
        )

    assert exc_info.value.error_code == error_code
