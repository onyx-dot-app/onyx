import json
from datetime import datetime, timedelta, timezone

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils import google_auth

_OVERRIDE = "http://localhost:9650/token"


def test_valid_oauth_creds_refresh_through_the_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid token is returned without a refresh. The client refreshes it
    later, so it must already point at the overridden token endpoint."""
    monkeypatch.setattr(google_auth, "GOOGLE_API_TOKEN_URI", _OVERRIDE)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)
    token_json = json.dumps(
        {
            "client_id": "client",
            "client_secret": "secret",
            "refresh_token": "refresh",
            "token": "access",
            "expiry": expiry.isoformat() + "Z",
        }
    )

    creds = google_auth.get_google_oauth_creds(
        token_json_str=token_json, source=DocumentSource.GOOGLE_DRIVE
    )

    assert creds is not None
    assert creds.valid
    assert creds.token_uri == _OVERRIDE
    assert creds.expiry is not None
    assert abs((creds.expiry - expiry).total_seconds()) < 1
