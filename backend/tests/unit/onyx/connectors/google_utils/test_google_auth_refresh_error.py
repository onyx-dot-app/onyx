import json
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from google.auth.exceptions import RefreshError

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)


def _make_credentials_dict() -> dict[str, str]:
    return {
        DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: json.dumps(
            {
                "type": "service_account",
                "project_id": "test",
                "private_key_id": "x",
                "private_key": "x",
                "client_email": "sa@test.iam.gserviceaccount.com",
                "client_id": "1",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        ),
        DB_CREDENTIALS_PRIMARY_ADMIN_KEY: "admin@test.com",
    }


@patch("onyx.connectors.google_utils.google_auth._refresh_service_account_creds")
def test_persistent_refresh_error_converted_to_permission_error(
    mock_refresh: MagicMock,
) -> None:
    """After the retry layer inside _refresh_service_account_creds gives up
    (re-raising RefreshError), get_google_creds must convert that into a
    PermissionError so callers can treat it as a "truly given up"
    credential-invalid signal rather than an unhandled exception."""
    mock_refresh.side_effect = RefreshError(
        "invalid_grant: Invalid grant: account not found"
    )
    creds_dict = _make_credentials_dict()
    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = False

    with patch(
        "onyx.connectors.google_utils.google_auth."
        "ServiceAccountCredentials.from_service_account_info",
        return_value=mock_creds,
    ):
        with pytest.raises(PermissionError) as exc_info:
            get_google_creds(creds_dict, DocumentSource.GOOGLE_DRIVE)

    assert "after retries" in str(exc_info.value).lower()
    assert "revoked" in str(exc_info.value).lower()
    assert isinstance(exc_info.value.__cause__, RefreshError)


@patch("onyx.connectors.google_utils.google_auth._refresh_service_account_creds")
def test_transient_refresh_error_recovered_via_retry(
    mock_refresh: MagicMock,
) -> None:
    """A transient RefreshError that succeeds on a later attempt should not
    bubble out: the tenacity-decorated helper retries, so the outer
    PermissionError conversion never fires."""
    creds_dict = _make_credentials_dict()
    mock_creds = MagicMock()

    # First call: not yet valid (forces refresh path).
    # Refresh itself is mocked to no-op (success) and after it we flip valid.
    call_counter = {"n": 0}

    def fake_refresh(_creds: object) -> None:
        call_counter["n"] += 1
        mock_creds.valid = True

    mock_refresh.side_effect = fake_refresh
    mock_creds.valid = False
    mock_creds.expired = False

    with patch(
        "onyx.connectors.google_utils.google_auth."
        "ServiceAccountCredentials.from_service_account_info",
        return_value=mock_creds,
    ):
        creds, _ = get_google_creds(creds_dict, DocumentSource.GOOGLE_DRIVE)

    assert creds is mock_creds
    assert call_counter["n"] == 1
