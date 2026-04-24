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


def test_refresh_error_converted_to_permission_error() -> None:
    """A google.auth RefreshError during a service-account refresh must be
    converted to a PermissionError so callers can handle revoked credentials
    cleanly instead of treating it as an unhandled Celery exception."""
    creds_dict = _make_credentials_dict()
    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = False
    mock_creds.refresh.side_effect = RefreshError(
        "invalid_grant: Invalid grant: account not found"
    )

    with patch(
        "onyx.connectors.google_utils.google_auth."
        "ServiceAccountCredentials.from_service_account_info",
        return_value=mock_creds,
    ):
        with pytest.raises(PermissionError) as exc_info:
            get_google_creds(creds_dict, DocumentSource.GOOGLE_DRIVE)

    assert "service account credentials" in str(exc_info.value).lower()
    assert "revoked" in str(exc_info.value).lower()
    mock_creds.refresh.assert_called_once()


def test_refresh_error_preserves_original_cause() -> None:
    """The chained exception should expose the original RefreshError via
    ``__cause__`` for debugging."""
    creds_dict = _make_credentials_dict()
    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = False
    original = RefreshError("boom")
    mock_creds.refresh.side_effect = original

    with patch(
        "onyx.connectors.google_utils.google_auth."
        "ServiceAccountCredentials.from_service_account_info",
        return_value=mock_creds,
    ):
        with pytest.raises(PermissionError) as exc_info:
            get_google_creds(creds_dict, DocumentSource.GOOGLE_DRIVE)

    assert exc_info.value.__cause__ is original
