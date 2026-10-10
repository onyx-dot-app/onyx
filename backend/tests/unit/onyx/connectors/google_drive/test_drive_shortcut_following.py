from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.google_drive.constants import (
    DRIVE_FOLDER_TYPE,
    DRIVE_RESOURCE_KEY_FIELD,
    DRIVE_RESOURCE_KEY_HEADER,
    DRIVE_SHORTCUT_TYPE,
)
from onyx.connectors.google_drive.doc_conversion import (
    convert_drive_item_to_document,
)
from onyx.connectors.google_drive.file_retrieval import (
    DriveFileFieldType,
    _get_files_in_parent,
    crawl_folders_for_files,
)
from onyx.connectors.google_drive.models import DriveRetrievalStage
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
)

_GATEWAY_MODULE = "onyx.connectors.google_drive.source_operations"
_USER = "user@example.com"
_PDF_MIME_TYPE = "application/pdf"


class _FakeRequest:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.headers: dict[str, str] = {}

    def execute(self) -> dict[str, Any]:
        return self._response


class _FakeFilesResource:
    def __init__(self, files_by_id: dict[str, dict[str, Any]]) -> None:
        self.files_by_id = files_by_id
        self.get_calls: list[dict[str, Any]] = []
        self.get_requests: list[_FakeRequest] = []

    def list(self, **_kwargs: object) -> object:
        return object()

    def get(self, **kwargs: Any) -> _FakeRequest:
        if "resourceKey" in kwargs:
            raise TypeError("Got an unexpected keyword argument resourceKey")
        self.get_calls.append(kwargs)
        request = _FakeRequest(self.files_by_id[kwargs["fileId"]])
        self.get_requests.append(request)
        return request

    def get_media(self, **kwargs: Any) -> _FakeRequest:
        if "resourceKey" in kwargs:
            raise TypeError("Got an unexpected keyword argument resourceKey")
        self.get_calls.append(kwargs)
        request = _FakeRequest(self.files_by_id.get(kwargs["fileId"], {}))
        self.get_requests.append(request)
        return request


class _FakeDriveService:
    def __init__(self, files_by_id: dict[str, dict[str, Any]]) -> None:
        self.files_resource = _FakeFilesResource(files_by_id)

    def files(self) -> _FakeFilesResource:
        return self.files_resource


@contextmanager
def _gateway(service: "_FakeDriveService") -> Iterator[GoogleDriveSourceOperations]:
    """A real gateway whose Drive service is the fake."""
    ops = GoogleDriveSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(None, "google_drive", {})
    )
    with patch.object(GoogleDriveSourceOperations, "_drive", return_value=service):
        yield ops


def _shortcut(
    shortcut_id: str,
    target_id: str,
    target_mime_type: str,
    target_resource_key: str | None = None,
) -> dict[str, Any]:
    shortcut_details = {
        "targetId": target_id,
        "targetMimeType": target_mime_type,
    }
    if target_resource_key:
        shortcut_details["targetResourceKey"] = target_resource_key

    return {
        "id": shortcut_id,
        "name": shortcut_id,
        "mimeType": DRIVE_SHORTCUT_TYPE,
        "shortcutDetails": shortcut_details,
    }


def _target_file(file_id: str, parent_id: str) -> dict[str, Any]:
    return {
        "id": file_id,
        "name": file_id,
        "mimeType": _PDF_MIME_TYPE,
        "parents": [parent_id],
        "webViewLink": f"https://drive.google.com/file/d/{file_id}",
    }


def _target_folder(folder_id: str) -> dict[str, Any]:
    return {
        "id": folder_id,
        "name": folder_id,
        "mimeType": DRIVE_FOLDER_TYPE,
        "parents": ["real_parent"],
        "webViewLink": f"https://drive.google.com/drive/folders/{folder_id}",
    }


def _file_query_parent(q: str) -> str:
    return q.split("'")[-2]


def _folder_query_parent(q: str) -> str | None:
    parts = q.split("'")
    return parts[-2] if len(parts) > 1 and " in parents" in q else None


def test_shortcut_to_file_yields_target_with_true_parent() -> None:
    target = _target_file("target_file", "true_parent")
    service = _FakeDriveService(
        {
            "shortcut_file": _shortcut("shortcut_file", "target_file", _PDF_MIME_TYPE),
            "target_file": target,
        }
    )

    def _fake_paginated_retrieval(**_kwargs: object) -> Iterator[dict[str, Any]]:
        yield _shortcut("shortcut_file", "target_file", _PDF_MIME_TYPE)

    with (
        _gateway(service) as ops,
        patch(
            f"{_GATEWAY_MODULE}.execute_paginated_retrieval",
            side_effect=_fake_paginated_retrieval,
        ),
    ):
        files = list(
            _get_files_in_parent(
                ops=ops,
                user_email=_USER,
                parent_id="shortcut_parent",
                field_type=DriveFileFieldType.STANDARD,
            )
        )

    assert files == [target]
    assert service.files_resource.get_calls[0]["fileId"] == "target_file"
    assert len(service.files_resource.get_calls) == 1


def test_shortcut_resolution_uses_shortcut_modified_time() -> None:
    target = _target_file("target_file", "true_parent")
    target["modifiedTime"] = "2024-01-15T00:00:00Z"
    service = _FakeDriveService(
        {
            "shortcut_file": _shortcut("shortcut_file", "target_file", _PDF_MIME_TYPE),
            "target_file": target,
        }
    )

    def _fake_paginated_retrieval(**_kwargs: object) -> Iterator[dict[str, Any]]:
        shortcut = _shortcut("shortcut_file", "target_file", _PDF_MIME_TYPE)
        shortcut["modifiedTime"] = "2026-06-02T00:00:00Z"
        yield shortcut

    with (
        _gateway(service) as ops,
        patch(
            f"{_GATEWAY_MODULE}.execute_paginated_retrieval",
            side_effect=_fake_paginated_retrieval,
        ),
    ):
        files = list(
            _get_files_in_parent(
                ops=ops,
                user_email=_USER,
                parent_id="shortcut_parent",
                field_type=DriveFileFieldType.STANDARD,
            )
        )

    assert len(files) == 1
    # the retrieved item keeps the shortcut's modifiedTime — the value the
    # listing was filtered/ordered by — so it stays within the requested range
    assert files[0]["modifiedTime"] == "2026-06-02T00:00:00Z"
    assert files[0]["id"] == "target_file"


def test_shortcut_to_resource_key_file_uses_header() -> None:
    target = _target_file("target_file", "true_parent")
    service = _FakeDriveService(
        {
            "shortcut_file": _shortcut(
                "shortcut_file",
                "target_file",
                _PDF_MIME_TYPE,
                target_resource_key="resource_key",
            ),
            "target_file": target,
        }
    )

    def _fake_paginated_retrieval(**_kwargs: object) -> Iterator[dict[str, Any]]:
        yield _shortcut(
            "shortcut_file",
            "target_file",
            _PDF_MIME_TYPE,
            target_resource_key="resource_key",
        )

    with (
        _gateway(service) as ops,
        patch(
            f"{_GATEWAY_MODULE}.execute_paginated_retrieval",
            side_effect=_fake_paginated_retrieval,
        ),
    ):
        files = list(
            _get_files_in_parent(
                ops=ops,
                user_email=_USER,
                parent_id="shortcut_parent",
                field_type=DriveFileFieldType.STANDARD,
            )
        )

    assert files == [target]
    assert service.files_resource.get_calls[0]["fileId"] == "target_file"
    assert "resourceKey" not in service.files_resource.get_calls[0]
    assert service.files_resource.get_requests[0].headers == {
        DRIVE_RESOURCE_KEY_HEADER: "target_file/resource_key"
    }
    assert target[DRIVE_RESOURCE_KEY_FIELD] == "resource_key"


def test_resource_key_download_uses_header() -> None:
    service = _FakeDriveService({})

    with (
        _gateway(service) as ops,
        patch(f"{_GATEWAY_MODULE}._download", return_value=b"content") as mock_download,
    ):
        content = ops.download_file(
            user_email=_USER,
            file_id="target_file",
            size_threshold=1_000,
            resource_key="resource_key",
        )

    assert content == b"content"
    assert service.files_resource.get_calls[0] == {"fileId": "target_file"}
    assert service.files_resource.get_requests[0].headers == {
        DRIVE_RESOURCE_KEY_HEADER: "target_file/resource_key"
    }
    mock_download.assert_called_once()


def test_shortcut_to_folder_crawls_target_folder() -> None:
    child = _target_file("child_file", "target_folder")
    service = _FakeDriveService(
        {
            "shortcut_folder": _shortcut(
                "shortcut_folder", "target_folder", DRIVE_FOLDER_TYPE
            ),
            "target_folder": _target_folder("target_folder"),
        }
    )

    def _fake_paginated_retrieval(**kwargs: object) -> Iterator[dict[str, Any]]:
        q = str(kwargs["q"])
        if q.startswith("mimeType !="):
            parent_id = _file_query_parent(q)
            if parent_id == "target_folder":
                yield child
            return

        parent_id = _folder_query_parent(q)
        if parent_id == "root_folder":
            yield _shortcut("shortcut_folder", "target_folder", DRIVE_FOLDER_TYPE)

    traversed: set[str] = set()
    with (
        _gateway(service) as ops,
        patch(
            f"{_GATEWAY_MODULE}.execute_paginated_retrieval",
            side_effect=_fake_paginated_retrieval,
        ),
    ):
        files = list(
            crawl_folders_for_files(
                ops=ops,
                parent_id="root_folder",
                field_type=DriveFileFieldType.STANDARD,
                user_email=_USER,
                traversed_parent_ids=traversed,
                update_traversed_ids_func=traversed.add,
            )
        )

    assert len(files) == 1
    assert files[0].completion_stage == DriveRetrievalStage.FOLDER_FILES
    assert files[0].drive_file == child
    assert files[0].parent_id == "target_folder"
    assert "target_folder" in traversed
    assert "shortcut_folder" not in traversed


def test_folder_shortcut_cycle_stops_without_completed_folders() -> None:
    service = _FakeDriveService(
        {
            "shortcut_a_to_b": _shortcut(
                "shortcut_a_to_b", "folder_b", DRIVE_FOLDER_TYPE
            ),
            "shortcut_b_to_a": _shortcut(
                "shortcut_b_to_a", "folder_a", DRIVE_FOLDER_TYPE
            ),
            "folder_a": _target_folder("folder_a"),
            "folder_b": _target_folder("folder_b"),
        }
    )
    folder_queries: list[str] = []

    def _fake_paginated_retrieval(**kwargs: object) -> Iterator[dict[str, Any]]:
        q = str(kwargs["q"])
        if q.startswith("mimeType !="):
            return

        parent_id = _folder_query_parent(q)
        folder_queries.append(parent_id or "")
        if parent_id == "folder_a":
            yield {
                "id": "shortcut_a_to_b",
                "name": "Shortcut A to B",
                "mimeType": DRIVE_SHORTCUT_TYPE,
            }
        if parent_id == "folder_b":
            yield {
                "id": "shortcut_b_to_a",
                "name": "Shortcut B to A",
                "mimeType": DRIVE_SHORTCUT_TYPE,
            }

    traversed: set[str] = set()
    with (
        _gateway(service) as ops,
        patch(
            f"{_GATEWAY_MODULE}.execute_paginated_retrieval",
            side_effect=_fake_paginated_retrieval,
        ),
    ):
        files = list(
            crawl_folders_for_files(
                ops=ops,
                parent_id="folder_a",
                field_type=DriveFileFieldType.STANDARD,
                user_email=_USER,
                traversed_parent_ids=traversed,
                update_traversed_ids_func=traversed.add,
            )
        )

    assert files == []
    assert folder_queries == ["folder_a", "folder_b"]
    assert traversed == set()


def test_traversed_parent_still_crawls_untraversed_child_folder() -> None:
    child = _target_file("child_file", "child_folder")
    service = _FakeDriveService({})
    file_query_parents: list[str] = []

    def _fake_paginated_retrieval(**kwargs: object) -> Iterator[dict[str, Any]]:
        q = str(kwargs["q"])
        if q.startswith("mimeType !="):
            parent_id = _file_query_parent(q)
            file_query_parents.append(parent_id)
            if parent_id == "child_folder":
                yield child
            return

        parent_id = _folder_query_parent(q)
        if parent_id == "root_folder":
            yield {
                "id": "child_folder",
                "name": "Child Folder",
                "mimeType": DRIVE_FOLDER_TYPE,
            }

    traversed = {"root_folder"}
    with (
        _gateway(service) as ops,
        patch(
            f"{_GATEWAY_MODULE}.execute_paginated_retrieval",
            side_effect=_fake_paginated_retrieval,
        ),
    ):
        files = list(
            crawl_folders_for_files(
                ops=ops,
                parent_id="root_folder",
                field_type=DriveFileFieldType.STANDARD,
                user_email=_USER,
                traversed_parent_ids=traversed,
                update_traversed_ids_func=traversed.add,
            )
        )

    assert len(files) == 1
    assert files[0].drive_file == child
    assert file_query_parents == ["child_folder"]
    assert "child_folder" in traversed


def test_raw_shortcut_conversion_logs_bug_guard(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    shortcut = _shortcut("shortcut_file", "target_file", _PDF_MIME_TYPE)

    result = convert_drive_item_to_document(
        ops=MagicMock(spec=GoogleDriveSourceOperations),
        allow_images=False,
        size_threshold=10_000,
        permission_sync_context=None,
        retriever_emails=[_USER],
        file=shortcut,
    )

    assert result is None
    assert "bug: raw shortcut/folder reached document conversion" in caplog.text
