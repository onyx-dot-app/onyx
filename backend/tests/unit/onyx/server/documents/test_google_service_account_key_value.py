import json

import pytest

from onyx.configs.constants import DocumentSource
from onyx.server.documents.draft_credentials import (
    validate_google_service_account_key,
)

_KEY: dict[str, str] = {
    "type": "service_account",
    "project_id": "project",
    "private_key_id": "key-id",
    "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
    "client_email": "indexer@project.iam.gserviceaccount.com",
    "client_id": "123",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/x",
    "universe_domain": "googleapis.com",
}


def _credential_json(key: object) -> dict[str, object]:
    return {
        "google_primary_admin": "admin@example.com",
        "google_service_account_key": key,
        "authentication_method": "uploaded",
    }


def test_accepts_a_service_account_key() -> None:
    validate_google_service_account_key(
        DocumentSource.GOOGLE_DRIVE, _credential_json(json.dumps(_KEY))
    )


def test_ignores_an_account_without_a_key() -> None:
    validate_google_service_account_key(
        DocumentSource.GOOGLE_DRIVE, {"google_tokens": "{}"}
    )


def test_ignores_other_sources() -> None:
    validate_google_service_account_key(
        DocumentSource.SLACK, _credential_json("not json")
    )


@pytest.mark.parametrize(
    "key",
    [
        "not json",
        json.dumps({"web": {"client_id": "x"}}),
        json.dumps({**_KEY, "type": "authorized_user"}),
        _KEY,
    ],
)
def test_rejects_anything_else(key: object) -> None:
    with pytest.raises(ValueError):
        validate_google_service_account_key(
            DocumentSource.GOOGLE_DRIVE, _credential_json(key)
        )
