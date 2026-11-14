"""Corpus shapes seen on a live Workspace, against main's Google Drive
connector and the mock server: bulk uploads, external files shared with
several users, OAuth credentials and folder targets."""

import base64
import json
import re
from collections import Counter
from typing import Any

import pytest

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.models import ConnectorFailure, Document, SlimDocument
from tests.external_dependency_unit.connectors.google_drive.conftest import MockDrive
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

_FILE_ID = re.compile(r"/(?:d|folders)/([A-Za-z0-9_-]+)")
_BULK_START = "2025-06-01T07:58:00.000Z"
_BASE_CORPUS: dict[str, Any] = {
    "num_users": 4,
    "num_groups": 1,
    "num_shared_drives": 2,
    "files_per_shared_drive": 10,
    "files_per_user": 6,
    "folders_per_container": 3,
    "shortcut_fraction": 0,
    # Only plain text: it converts without a file store, an extraction
    # service or the Docs API quota. The server merges this with the default
    # weights, so the other types need a weight of 0.
    "mime_weights": {
        "application/vnd.google-apps.document": 0,
        "application/vnd.google-apps.spreadsheet": 0,
        "application/vnd.google-apps.presentation": 0,
        "application/pdf": 0,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": 0,
        "text/markdown": 0,
        "text/plain": 1,
    },
}
_SHAPES_CORPUS: dict[str, Any] = {
    **_BASE_CORPUS,
    "external_shares": {"owners": 2, "files": 40, "recipients": 3},
    "bulk_uploads": [
        # More files in one second than one listing page holds.
        {"count": 1_100, "container": "external", "index": 0},
        {
            "count": 150,
            "bursts": 3,
            "spacing_seconds": 2,
            "start": "2025-06-02T10:00:00Z",
            "container": "my_drive",
        },
        {
            "count": 120,
            "start": "2025-06-03T10:00:00Z",
            "container": "shared_drive",
            "index": 1,
        },
    ],
    "folder_trees": [
        {"container": "my_drive", "index": 2, "depth": 3, "deepest_folder_files": 40}
    ],
}


def _file_id(document_id: str) -> str:
    match = _FILE_ID.search(document_id)
    return match.group(1) if match else document_id


def _slim_ids(connector: GoogleDriveConnector) -> list[str]:
    return [
        _file_id(doc.id)
        for batch in connector.retrieve_all_slim_docs()
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]


def _assert_exact(listed: list[str], expected: set[str]) -> None:
    duplicates = [i for i, n in Counter(listed).items() if n > 1]
    assert not duplicates, f"{len(duplicates)} files listed more than once"
    assert set(listed) - expected == set(), "files listed that are not expected"
    assert expected - set(listed) == set(), "expected files not listed"


def _oauth_connector(
    mock: MockDrive, email: str, **kwargs: Any
) -> GoogleDriveConnector:
    tokens = mock.client.get("/_mock/oauth-credentials", params={"email": email})
    tokens.raise_for_status()
    connector = GoogleDriveConnector(**kwargs)
    connector.load_credentials(
        {
            "google_tokens": json.dumps(tokens.json()),
            "google_primary_admin": email,
            "authentication_method": "uploaded",
        }
    )
    return connector


def _access_token(mock: MockDrive, email: str) -> str:
    refresh_token = mock.client.get(
        "/_mock/oauth-credentials", params={"email": email}
    ).json()["refresh_token"]
    response = mock.client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def _user_ids(mock: MockDrive, email: str, scope: str) -> set[str]:
    response = mock.client.get(
        f"/_mock/corpus/users/{email}/content-ids", params={"scope": scope}
    )
    response.raise_for_status()
    return set(response.json()["file_ids"])


def test_bulk_uploads_keep_one_whole_second_time(own_mock_drive: MockDrive) -> None:
    own_mock_drive.set_corpus(_SHAPES_CORPUS)
    summary = own_mock_drive.client.get("/_mock/corpus/summary").json()
    recipient = summary["external_recipient_emails"][0]
    token = _access_token(own_mock_drive, recipient)

    files: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params = {
            "q": f"modifiedTime = '{_BULK_START}'",
            "orderBy": "modifiedTime",
            "pageSize": "1000",
            "fields": "nextPageToken,files(id,modifiedTime,owners(emailAddress))",
        }
        if page_token:
            params["pageToken"] = page_token
        page = own_mock_drive.client.get(
            "/drive/v3/files",
            params=params,
            headers={"authorization": f"Bearer {token}"},
        ).json()
        files.extend(page["files"])
        page_token = page.get("nextPageToken")
        if not page_token:
            break

    assert len(files) == 1_100
    assert {f["modifiedTime"] for f in files} == {_BULK_START}
    assert {f["owners"][0]["emailAddress"] for f in files} == {"ext1@gmail.com"}


def test_external_owners_cannot_be_impersonated(own_mock_drive: MockDrive) -> None:
    own_mock_drive.set_corpus(_SHAPES_CORPUS)
    key = own_mock_drive.client.get("/_mock/service-account-key").json()

    def assertion(subject: str) -> str:
        claims = {"iss": key["client_email"], "sub": subject, "scope": "drive"}
        body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
        return f"e30.{body.rstrip('=')}.c2ln"

    grant = "urn:ietf:params:oauth:grant-type:jwt-bearer"
    external = own_mock_drive.client.post(
        "/token", data={"grant_type": grant, "assertion": assertion("ext1@gmail.com")}
    )
    assert external.status_code == 400
    assert external.json()["error"] == "invalid_grant"
    internal = own_mock_drive.client.post(
        "/token",
        data={"grant_type": grant, "assertion": assertion("user1@onyx-mock.test")},
    )
    assert internal.status_code == 200
    no_oauth = own_mock_drive.client.get(
        "/_mock/oauth-credentials", params={"email": "ext1@gmail.com"}
    )
    assert no_oauth.status_code == 404


def test_service_account_indexes_every_shape(own_mock_drive: MockDrive) -> None:
    """Main's connector indexes bulk uploads, external shares and a folder tree
    once each, with no gaps."""
    own_mock_drive.set_corpus(_SHAPES_CORPUS)
    expected = own_mock_drive.content_file_ids()

    _assert_exact(_slim_ids(own_mock_drive.build_connector()), expected)

    outputs = load_everything_from_checkpoint_connector(
        own_mock_drive.build_connector(), 0, 2_000_000_000
    )
    items = [item for output in outputs for item in output.items]
    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert not failures, failures[:3]
    _assert_exact(
        [_file_id(item.id) for item in items if isinstance(item, Document)], expected
    )


@pytest.mark.parametrize(
    "my_drives,shared_with_me,shared_drives,scope",
    [
        (True, True, True, "all_drives"),
        (True, False, False, "owned"),
        (False, True, False, "shared_with_me"),
    ],
)
def test_oauth_lists_the_users_corpus(
    own_mock_drive: MockDrive,
    my_drives: bool,
    shared_with_me: bool,
    shared_drives: bool,
    scope: str,
) -> None:
    own_mock_drive.set_corpus(_SHAPES_CORPUS)
    # A recipient of the external shares, with a My Drive and shared drives.
    email = "user1@onyx-mock.test"
    expected = _user_ids(own_mock_drive, email, scope)
    assert expected

    connector = _oauth_connector(
        own_mock_drive,
        email,
        include_my_drives=my_drives,
        include_files_shared_with_me=shared_with_me,
        include_shared_drives=shared_drives,
    )
    _assert_exact(_slim_ids(connector), expected)


@pytest.mark.parametrize("container,index", [("my_drive", 2), ("shared_drive", 1)])
def test_folder_target_lists_exactly_its_subtree(
    own_mock_drive: MockDrive, container: str, index: int
) -> None:
    own_mock_drive.set_corpus(
        {
            **_BASE_CORPUS,
            "folder_trees": [
                {
                    "container": container,
                    "index": index,
                    "depth": 4,
                    "branching": 2,
                    "files_per_folder": 2,
                    # More files in one folder than one listing page holds.
                    "deepest_folder_files": 1_100,
                },
                # A second tree in the same container must not be listed.
                {"container": container, "index": index, "depth": 1},
            ],
        }
    )
    summary = own_mock_drive.client.get("/_mock/corpus/summary").json()
    root_id = summary["folder_tree_root_ids"][0]
    expected = set(
        own_mock_drive.client.get(
            f"/_mock/corpus/folders/{root_id}/content-ids"
        ).json()["file_ids"]
    )
    # 31 folders with 2 files each, and the large folder.
    assert len(expected) == 31 * 2 + 1_100

    connector = own_mock_drive.build_connector(
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=f"https://drive.google.com/drive/folders/{root_id}",
    )
    _assert_exact(_slim_ids(connector), expected)


def _list_files(mock: MockDrive, email: str, **params: str) -> list[dict[str, Any]]:
    response = mock.client.get(
        "/drive/v3/files",
        params={"pageSize": "1000", "fields": "files(id,modifiedTime)", **params},
        headers={"authorization": f"Bearer {_access_token(mock, email)}"},
    )
    response.raise_for_status()
    return list(response.json()["files"])


def test_bulk_upload_start_times_are_read_as_utc(own_mock_drive: MockDrive) -> None:
    """A start with no zone is UTC, and a start with an offset is converted.
    The time that the API returns is the time that a query compares."""
    own_mock_drive.set_corpus(
        {
            **_BASE_CORPUS,
            "bulk_uploads": [
                {"count": 3, "start": "2025-06-03T09:00:00"},
                {"count": 4, "start": "2025-06-04T12:00:00+02:00"},
            ],
        }
    )
    admin = own_mock_drive.client.get("/_mock/corpus/summary").json()["admin_email"]

    # A sort over every file compares these times with the generated ones.
    everything = _list_files(own_mock_drive, admin, orderBy="modifiedTime")
    no_zone = _list_files(
        own_mock_drive, admin, q="modifiedTime = '2025-06-03T09:00:00.000Z'"
    )
    offset = _list_files(
        own_mock_drive, admin, q="modifiedTime = '2025-06-04T10:00:00.000Z'"
    )

    assert len(no_zone) == 3
    assert len(offset) == 4
    assert {f["modifiedTime"] for f in offset} == {"2025-06-04T10:00:00.000Z"}
    # Each returned time finds its file again: no time is finer than the API shows.
    for file in everything[:20]:
        found = _list_files(
            own_mock_drive, admin, q=f"modifiedTime = '{file['modifiedTime']}'"
        )
        assert file["id"] in {f["id"] for f in found}


def test_a_config_change_works_with_a_bulk_upload_corpus(
    own_mock_drive: MockDrive,
) -> None:
    """The config has a datetime when the corpus has a bulk upload."""
    own_mock_drive.set_corpus({**_BASE_CORPUS, "bulk_uploads": [{"count": 2}]})

    response = own_mock_drive.client.patch(
        "/_mock/config", json={"latency": {"enabled": False}}
    )

    assert response.status_code == 200
    start = response.json()["corpus"]["bulk_uploads"][0]["start"]
    assert start.startswith("2025-06-01")


def test_an_infinite_latency_is_refused(own_mock_drive: MockDrive) -> None:
    response = own_mock_drive.client.patch(
        "/_mock/config",
        content='{"latency": {"metadata_ms": 1e309}}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
