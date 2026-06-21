from collections.abc import Iterator
from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from googleapiclient.discovery import Resource

from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.constants import DRIVE_SHORTCUT_TYPE
from onyx.connectors.google_drive.doc_conversion import convert_drive_item_to_document
from onyx.connectors.google_drive.file_retrieval import _get_files_in_parent
from onyx.connectors.google_drive.file_retrieval import crawl_folders_for_files
from onyx.connectors.google_drive.file_retrieval import DriveFileFieldType
from onyx.connectors.google_drive.models import DriveRetrievalStage

_FILE_RETRIEVAL_MODULE = "onyx.connectors.google_drive.file_retrieval"
_PDF_MIME_TYPE = "application/pdf"


class _FakeRequest:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    def execute(self) -> dict[str, Any]:
        return self._response


class _FakeFilesResource:
    def __init__(self, files_by_id: dict[str, dict[str, Any]]) -> None:
        self.files_by_id = files_by_id
        self.get_calls: list[dict[str, Any]] = []

    def list(self, **_kwargs: object) -> object:
        return object()

    def get(self, **kwargs: Any) -> _FakeRequest:
        self.get_calls.append(kwargs)
        return _FakeRequest(self.files_by_id[kwargs["fileId"]])


class _FakeDriveService:
    def __init__(self, files_by_id: dict[str, dict[str, Any]]) -> None:
        self.files_resource = _FakeFilesResource(files_by_id)

    def files(self) -> _FakeFilesResource:
        return self.files_resource


def _shortcut(
    shortcut_id: str,
    target_id: str,
    target_mime_type: str,
) -> dict[str, Any]:
    return {
        "id": shortcut_id,
        "name": shortcut_id,
        "mimeType": DRIVE_SHORTCUT_TYPE,
        "shortcutDetails": {
            "targetId": target_id,
            "targetMimeType": target_mime_type,
        },
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

    with patch(
        f"{_FILE_RETRIEVAL_MODULE}.execute_paginated_retrieval",
        side_effect=_fake_paginated_retrieval,
    ):
        files = list(
            _get_files_in_parent(
                service=cast(Resource, service),
                parent_id="shortcut_parent",
                field_type=DriveFileFieldType.STANDARD,
            )
        )

    assert files == [target]
    assert service.files_resource.get_calls[0]["fileId"] == "target_file"
    assert len(service.files_resource.get_calls) == 1


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
    with patch(
        f"{_FILE_RETRIEVAL_MODULE}.execute_paginated_retrieval",
        side_effect=_fake_paginated_retrieval,
    ):
        files = list(
            crawl_folders_for_files(
                service=cast(Resource, service),
                parent_id="root_folder",
                field_type=DriveFileFieldType.STANDARD,
                user_email="user@example.com",
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
    with patch(
        f"{_FILE_RETRIEVAL_MODULE}.execute_paginated_retrieval",
        side_effect=_fake_paginated_retrieval,
    ):
        files = list(
            crawl_folders_for_files(
                service=cast(Resource, service),
                parent_id="folder_a",
                field_type=DriveFileFieldType.STANDARD,
                user_email="user@example.com",
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
    with patch(
        f"{_FILE_RETRIEVAL_MODULE}.execute_paginated_retrieval",
        side_effect=_fake_paginated_retrieval,
    ):
        files = list(
            crawl_folders_for_files(
                service=cast(Resource, service),
                parent_id="root_folder",
                field_type=DriveFileFieldType.STANDARD,
                user_email="user@example.com",
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
        creds=MagicMock(),
        allow_images=False,
        size_threshold=10_000,
        permission_sync_context=None,
        retriever_emails=["user@example.com"],
        file=shortcut,
    )

    assert result is None
    assert "bug: raw shortcut/folder reached document conversion" in caplog.text
