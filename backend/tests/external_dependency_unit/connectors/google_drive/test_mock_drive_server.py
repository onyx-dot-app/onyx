"""Request handling of the mock Google Drive server itself: settings
validation, tokens and query aliases."""

import base64
import json

from onyx.connectors.google_drive.source_operations import DriveCorpus
from tests.external_dependency_unit.connectors.google_drive.conftest import MockDrive

_SCOPE = "https://www.googleapis.com/auth/"


def test_unknown_or_invalid_settings_are_rejected(mock_drive: MockDrive) -> None:
    misspelled = mock_drive.client.patch(
        "/_mock/config", json={"quota": {"user_unit_per_minute": 20_000}}
    )
    assert misspelled.status_code == 400

    negative_weight = mock_drive.client.post(
        "/_mock/corpus",
        json={"mime_weights": {"text/plain": 2, "application/pdf": -1}},
    )
    assert negative_weight.status_code == 400


def test_refresh_cannot_add_scopes(mock_drive: MockDrive) -> None:
    summary = mock_drive.client.get("/_mock/corpus/summary").json()
    credentials = mock_drive.client.get(
        "/_mock/oauth-credentials", params={"email": summary["admin_email"]}
    ).json()
    form = {
        "grant_type": "refresh_token",
        "refresh_token": credentials["refresh_token"],
    }

    granted = mock_drive.client.post(
        "/token", data={**form, "scope": _SCOPE + "drive.readonly"}
    )
    broader = mock_drive.client.post(
        "/token", data={**form, "scope": _SCOPE + "documents"}
    )

    assert granted.status_code == 200
    assert broader.status_code == 400
    assert broader.json()["error"] == "invalid_scope"


def test_malformed_token_expiry_is_unauthenticated(mock_drive: MockDrive) -> None:
    summary = mock_drive.client.get("/_mock/corpus/summary").json()
    payload = {"e": summary["admin_email"], "s": [_SCOPE + "drive"], "x": "invalid"}
    token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    response = mock_drive.client.get(
        "/drive/v3/files", headers={"Authorization": f"Bearer mockat.{token}"}
    )

    assert response.status_code == 401


def test_root_alias_lists_the_my_drive_root(mock_drive: MockDrive) -> None:
    connector = mock_drive.build_connector()
    admin = connector.primary_admin_email
    root_id = connector.ops.get_root_folder_id(user_email=admin)

    # A listing with no page limit yields no page token.
    children = [
        child
        for child in connector.ops.list_files(
            variant=DriveCorpus.USER,
            user_email=admin,
            query="'root' in parents and trashed = false",
            fields="nextPageToken, files(id, parents)",
        )
        if not isinstance(child, str)
    ]

    assert children
    assert all(root_id in child["parents"] for child in children)
