"""OAuth shared-drive retrieval must resume from the saved page token.

Shared-drive listing fetches SHARED_DRIVE_PAGES_PER_CHECKPOINT pages per
checkpoint span, then emits a page token so the next span can continue.
A regression here silently truncates large shared drives: the token is
dropped, the stage machine advances to FOLDER_FILES, and the folder crawl
skips everything because the drive and its folders are already marked
traversed (https://github.com/onyx-dot-app/onyx/issues/14165).

Also covers the pause-before-first-file case: a span can emit a page token
before the current drive yields any file (empty pages, or leading files all
dropped by shortcut resolution). The checkpoint must attribute that token to
the drive being listed, not to the previous drive, or the resume re-lists the
wrong drive and the paused one restarts from page 1 on every span.
"""

import copy
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

import onyx.connectors.google_drive.connector as connector_module
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.file_retrieval import DriveFileFieldType
from onyx.connectors.google_drive.models import DriveRetrievalStage
from onyx.connectors.interfaces import SecondsSinceUnixEpoch

_USER = "user@example.com"
_PAGE_SIZE = 3

FakeRetrieval = Callable[..., Iterator[dict[str, Any] | str]]


def _drive_file(index: int) -> dict[str, Any]:
    modified = datetime(2024, 1, 1, index, 0, 0, tzinfo=timezone.utc)
    return {
        "id": f"file_{index}",
        "name": f"file_{index}",
        "modifiedTime": modified.isoformat(),
        "webViewLink": f"https://drive.google.com/file/d/file_{index}",
    }


def _make_fake_get_files_in_shared_drive(
    files_by_drive: dict[str, list[dict[str, Any]]],
    filtered_first_span_drives: frozenset[str] = frozenset(),
) -> FakeRetrieval:
    """Pages through a drive's files; the page token encodes the next offset.

    Drives in filtered_first_span_drives yield only a page token on their
    first span, simulating leading pages whose files were all dropped by
    shortcut resolution.
    """

    def _fake(
        service: Any,  # noqa: ARG001
        drive_id: str,
        field_type: DriveFileFieldType,  # noqa: ARG001
        max_num_pages: int,
        update_traversed_ids_func: Callable[[str], None] = lambda _: None,
        cache_folders: bool = True,  # noqa: ARG001
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG001
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG001
        page_token: str | None = None,
    ) -> Iterator[dict[str, Any] | str]:
        if drive_id in filtered_first_span_drives and page_token is None:
            yield "0"
            return
        files = files_by_drive[drive_id]
        offset = int(page_token) if page_token else 0
        for _ in range(max_num_pages):
            if offset >= len(files):
                return
            for file in files[offset : offset + _PAGE_SIZE]:
                update_traversed_ids_func(drive_id)
                yield file
            offset += _PAGE_SIZE
        if offset < len(files):
            yield str(offset)

    return _fake


def _build_oauth_connector(
    monkeypatch: pytest.MonkeyPatch,
    drive_ids: list[str],
    fake_retrieval: FakeRetrieval,
) -> GoogleDriveConnector:
    urls = ",".join(
        f"https://drive.google.com/drive/folders/{drive_id}" for drive_id in drive_ids
    )
    connector = GoogleDriveConnector(shared_drive_urls=urls)
    # Any non-service-account creds select the OAuth retrieval path.
    connector._creds = MagicMock()
    connector._primary_admin_email = _USER
    monkeypatch.setattr(connector, "get_all_drive_ids", lambda: set(drive_ids))
    monkeypatch.setattr(connector_module, "get_drive_service", MagicMock())
    monkeypatch.setattr(connector_module, "get_files_in_shared_drive", fake_retrieval)
    return connector


def _run_all_checkpoint_spans(
    connector: GoogleDriveConnector, max_spans: int
) -> list[str]:
    """Mimics the _load_from_checkpoint span loop, returning retrieved ids."""
    checkpoint = connector.build_dummy_checkpoint()
    retrieved_ids: list[str] = []
    for _ in range(max_spans):
        if checkpoint.completion_stage == DriveRetrievalStage.DONE:
            return retrieved_ids
        checkpoint = copy.deepcopy(checkpoint)
        connector._retrieved_folder_and_drive_ids = (
            checkpoint.retrieved_folder_and_drive_ids
        )
        retrieved_ids.extend(
            file.drive_file["id"]
            for file in connector._fetch_drive_items(
                field_type=DriveFileFieldType.STANDARD,
                checkpoint=checkpoint,
                start=0,
                end=datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp(),
            )
        )
        checkpoint.retrieved_folder_and_drive_ids = (
            connector._retrieved_folder_and_drive_ids
        )
    raise AssertionError("retrieval never reached the DONE stage")


def _assert_retrieved_exactly(
    retrieved_ids: list[str], files_by_drive: dict[str, list[dict[str, Any]]]
) -> None:
    assert len(retrieved_ids) == len(set(retrieved_ids))
    expected_ids = [file["id"] for files in files_by_drive.values() for file in files]
    assert sorted(retrieved_ids) == sorted(expected_ids)


def test_oauth_shared_drive_retrieval_spans_all_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files_by_drive = {"drive_1": [_drive_file(i) for i in range(20)]}
    connector = _build_oauth_connector(
        monkeypatch,
        drive_ids=["drive_1"],
        fake_retrieval=_make_fake_get_files_in_shared_drive(files_by_drive),
    )

    retrieved_ids = _run_all_checkpoint_spans(connector, max_spans=40)

    _assert_retrieved_exactly(retrieved_ids, files_by_drive)


def test_oauth_shared_drive_token_before_any_file_resumes_same_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token pause before ANY file was ever yielded (empty drive first).

    The per-user stage is still START when the pause happens, so without a
    proactive stage update the resume branch is skipped, the token leaks into
    the empty drive's fresh listing, gets cleared there, and the paused drive
    restarts from page 1 on every span without ever completing.
    """
    files_by_drive: dict[str, list[dict[str, Any]]] = {
        "drive_a": [],
        "drive_b": [_drive_file(i) for i in range(14)],
    }
    connector = _build_oauth_connector(
        monkeypatch,
        drive_ids=["drive_a", "drive_b"],
        fake_retrieval=_make_fake_get_files_in_shared_drive(
            files_by_drive, filtered_first_span_drives=frozenset({"drive_b"})
        ),
    )

    retrieved_ids = _run_all_checkpoint_spans(connector, max_spans=40)

    _assert_retrieved_exactly(retrieved_ids, files_by_drive)


def test_oauth_shared_drive_token_before_first_file_resumes_same_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files_by_drive = {
        "drive_a": [_drive_file(i) for i in range(6)],
        "drive_b": [_drive_file(i) for i in range(6, 20)],
    }
    connector = _build_oauth_connector(
        monkeypatch,
        drive_ids=["drive_a", "drive_b"],
        fake_retrieval=_make_fake_get_files_in_shared_drive(
            files_by_drive, filtered_first_span_drives=frozenset({"drive_b"})
        ),
    )

    retrieved_ids = _run_all_checkpoint_spans(connector, max_spans=40)

    _assert_retrieved_exactly(retrieved_ids, files_by_drive)
