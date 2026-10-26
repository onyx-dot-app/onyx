"""The Drive corpus estimate against a fake gateway: it walks the resolved
scope with the count field mask, labels files by type, counts a file shared
with several users once, reads a drive the admin cannot list as its
organizer, reports what nobody can list, and stops on request with a lower
bound."""

import re
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.google_drive import corpus_estimate
from onyx.connectors.google_drive.constants import (
    DRIVE_FOLDER_TYPE,
    DRIVE_SHORTCUT_TYPE,
)
from onyx.connectors.google_drive.corpus_estimate import (
    CountStopped,
    drive_document_type,
    estimate_drive_corpus,
)
from onyx.connectors.google_drive.file_retrieval import (
    COUNT_FILE_FIELDS,
    FOLDER_FIELDS,
)
from onyx.connectors.google_drive.models import DriveCountScope, GDriveMimeType
from onyx.connectors.google_drive.source_operations import (
    DriveCorpus,
    GoogleDriveHttpError,
    GoogleDriveRefreshError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.models import CorpusEstimate, DocumentTypeLabel

ADMIN = "admin@co.com"
ALICE = "alice@co.com"
BOB = "bob@co.com"


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def owner_of(file: dict[str, Any]) -> str:
    return file["owners"][0]["emailAddress"]


def _file(
    file_id: str,
    mime_type: str = GDriveMimeType.DOC.value,
    owner: str = ALICE,
    drive_id: str | None = None,
    modified: str = "2024-06-01T00:00:00+00:00",
) -> dict[str, Any]:
    file: dict[str, Any] = {
        "id": file_id,
        "mimeType": mime_type,
        "modifiedTime": modified,
        "owners": [{"emailAddress": owner}],
    }
    if not mime_type.startswith("application/vnd.google-apps."):
        file["size"] = "10"
    if drive_id is not None:
        file["driveId"] = drive_id
    return file


def _scope(**overrides: Any) -> DriveCountScope:
    values: dict[str, Any] = {
        "include_shared_drives": False,
        "include_my_drives": False,
        "include_files_shared_with_me": False,
        "drives": {},
        "folders": {},
        "my_drive_emails": [],
    }
    values.update(overrides)
    return DriveCountScope(**values)


def _shortcut(file_id: str, target_id: str, target_type: str) -> dict[str, Any]:
    return {
        "id": file_id,
        "mimeType": DRIVE_SHORTCUT_TYPE,
        "modifiedTime": "2024-06-01T00:00:00+00:00",
        "shortcutDetails": {"targetId": target_id, "targetMimeType": target_type},
    }


class _Tenant:
    """Listings by (corpus, principal, drive) that the fake gateway serves."""

    def __init__(self) -> None:
        self.ops = MagicMock(spec=GoogleDriveSourceOperations)
        self.ops.list_files.side_effect = self._list_files
        self.drives: dict[str, list[dict[str, Any]]] = {}
        self.owned: dict[str, list[dict[str, Any]]] = {}
        self.visible: dict[str, list[dict[str, Any]]] = {}
        # Files and subfolders by parent folder.
        self.folders: dict[str, list[dict[str, Any]]] = {}
        self.subfolders: dict[str, list[dict[str, Any]]] = {}
        self.broken_users: set[str] = set()
        self.no_drive_users: set[str] = set()
        # Shortcut targets by id, as files.get returns them.
        self.targets: dict[str, dict[str, Any]] = {}
        # Drive sometimes answers a first page with no files and a token.
        self.leading_empty_page = False
        # An expired page token makes the gateway restart the query once.
        self.restart_once = False
        self.calls: list[dict[str, Any]] = []
        self.ops.get_file.side_effect = lambda **kwargs: self.targets.get(
            kwargs["file_id"]
        )

    def _list_files(self, **kwargs: Any) -> Iterator[dict[str, Any]]:
        self.calls.append(kwargs)
        parent = re.search(r"'([^']+)' in parents", kwargs["query"])
        if kwargs["fields"] == FOLDER_FIELDS:
            assert parent is not None
            return iter(self.subfolders.get(parent.group(1), []))
        assert kwargs["fields"] == COUNT_FILE_FIELDS
        assert kwargs["page_size"] in (corpus_estimate.COUNT_PAGE_SIZE, 1)
        email = kwargs["user_email"]
        if email in self.broken_users:
            raise GoogleDriveRefreshError(f"cannot act as {email}")
        if email in self.no_drive_users:
            raise GoogleDriveHttpError(
                status_code=401, reasons=(), access_denied=False, message="no Drive"
            )
        if parent is not None:
            files = self.folders.get(parent.group(1), [])
        elif kwargs["variant"] is DriveCorpus.DRIVE:
            files = self.drives.get(kwargs["drive_id"], [])
        elif "not 'me' in owners" in kwargs["query"]:
            files = [f for f in self.visible.get(email, []) if owner_of(f) != email]
        elif "'me' in owners" in kwargs["query"]:
            files = self.owned.get(email, [])
        else:
            files = self.visible.get(email, [])
        return self._page(files, kwargs)

    def _page(
        self, files: list[dict[str, Any]], kwargs: dict[str, Any]
    ) -> Iterator[Any]:
        """A sharded listing: the modifiedTime bounds of the query, ordered
        either way, paged, with a page token after ``max_num_pages`` pages.
        Without a page cap the listing runs to its end as the gateway does."""
        bounds = re.findall(r"modifiedTime (>=|<) '([^']+)'", kwargs["query"])
        low = next(_ts(v) for op, v in bounds if op == ">=")
        high = next(_ts(v) for op, v in bounds if op == "<")
        rows = sorted(
            (f for f in files if low <= _ts(f["modifiedTime"]) < high),
            key=lambda f: _ts(f["modifiedTime"]),
            reverse=kwargs.get("order_by", "").endswith(" desc"),
        )
        size = kwargs["page_size"]
        offset = int(kwargs.get("page_token") or 0)
        if self.restart_once and offset:
            self.restart_once = False
            offset = 0
        max_pages = kwargs.get("max_num_pages")
        pages = 0
        if self.leading_empty_page and not kwargs.get("page_token"):
            pages += 1
            if pages == max_pages:
                yield "0"
                return
        while offset < len(rows):
            if pages == max_pages:
                yield str(offset)
                return
            yield from rows[offset : offset + size]
            offset += size
            pages += 1


def _estimate(
    tenant: _Tenant,
    scope: DriveCountScope,
    should_stop: Callable[[], bool] = lambda: False,
    on_progress: Callable[[CorpusEstimate], None] = lambda _: None,
    end: float | None = None,
    is_service_account: bool = True,
) -> CorpusEstimate:
    return estimate_drive_corpus(
        tenant.ops,
        primary_admin_email=ADMIN,
        is_service_account=is_service_account,
        plan_scope=lambda: scope,
        start=None,
        end=end,
        should_stop=should_stop,
        on_progress=on_progress,
    )


def test_labels_cover_native_office_text_image_and_the_rest() -> None:
    assert drive_document_type(GDriveMimeType.DOC.value) is DocumentTypeLabel.DOCUMENT
    assert (
        drive_document_type(GDriveMimeType.WORD_DOC.value) is DocumentTypeLabel.DOCUMENT
    )
    assert (
        drive_document_type(GDriveMimeType.SPREADSHEET.value)
        is DocumentTypeLabel.SPREADSHEET
    )
    assert drive_document_type("text/csv") is DocumentTypeLabel.SPREADSHEET
    assert (
        drive_document_type(GDriveMimeType.PPT.value) is DocumentTypeLabel.PRESENTATION
    )
    assert (
        drive_document_type(GDriveMimeType.POWERPOINT.value)
        is DocumentTypeLabel.PRESENTATION
    )
    assert drive_document_type("application/pdf") is DocumentTypeLabel.PDF
    assert drive_document_type("text/x-python") is DocumentTypeLabel.TEXT
    assert drive_document_type("image/png") is DocumentTypeLabel.IMAGE
    assert (
        drive_document_type("application/vnd.google-apps.form")
        is DocumentTypeLabel.OTHER
    )
    assert drive_document_type("application/zip") is DocumentTypeLabel.OTHER


def test_shared_drives_and_my_drives_count_by_type() -> None:
    tenant = _Tenant()
    tenant.drives["d1"] = [
        _file("f1", drive_id="d1"),
        _file("f2", "application/pdf", drive_id="d1"),
        # A shortcut counts as its target. A folder shortcut is no document.
        {
            "id": "s1",
            "mimeType": DRIVE_SHORTCUT_TYPE,
            "modifiedTime": "2024-06-01T00:00:00+00:00",
            "shortcutDetails": {"targetMimeType": "application/pdf"},
        },
        {
            "id": "s2",
            "mimeType": DRIVE_SHORTCUT_TYPE,
            "modifiedTime": "2024-06-01T00:00:00+00:00",
            "shortcutDetails": {"targetMimeType": DRIVE_FOLDER_TYPE},
        },
    ]
    tenant.owned[ALICE] = [_file("a1"), _file("a2", "image/png")]
    tenant.owned[BOB] = [_file("b1", "text/plain", owner=BOB)]

    estimate = _estimate(
        tenant,
        _scope(
            include_shared_drives=True,
            include_my_drives=True,
            drives={"d1": ADMIN},
            my_drive_emails=[ADMIN, ALICE, BOB],
        ),
    )

    assert estimate.total_docs == 6
    assert estimate.docs_by_type == {
        DocumentTypeLabel.DOCUMENT: 2,
        DocumentTypeLabel.PDF: 2,
        DocumentTypeLabel.IMAGE: 1,
        DocumentTypeLabel.TEXT: 1,
    }
    # The fake lists no size on native Google files, so only the rest have bytes.
    assert estimate.bytes_by_type == {
        DocumentTypeLabel.PDF: 10,
        DocumentTypeLabel.IMAGE: 10,
        DocumentTypeLabel.TEXT: 10,
    }
    assert estimate.partial is False
    assert estimate.detail is None


def test_a_shared_file_counts_once_and_covered_copies_are_dropped() -> None:
    tenant = _Tenant()
    tenant.drives["d1"] = [_file("f1", drive_id="d1")]
    tenant.owned[ALICE] = [_file("a1")]
    external = _file("x1", "application/pdf", owner="someone@other.com")
    # Alice and Bob both see the external file. Bob also sees the drive file
    # and Alice's file, which their own partitions already counted.
    tenant.visible[ALICE] = [external, _file("a1")]
    tenant.visible[BOB] = [external, _file("f1", drive_id="d1"), _file("a1")]

    estimate = _estimate(
        tenant,
        _scope(
            include_shared_drives=True,
            include_my_drives=True,
            include_files_shared_with_me=True,
            drives={"d1": ADMIN},
            my_drive_emails=[ADMIN, ALICE, BOB],
        ),
    )

    assert estimate.docs_by_type == {
        DocumentTypeLabel.DOCUMENT: 2,
        DocumentTypeLabel.PDF: 1,
    }


def test_each_drive_is_listed_as_the_user_the_run_plans() -> None:
    tenant = _Tenant()
    tenant.drives["d1"] = [_file("f1", drive_id="d1")]
    tenant.drives["d2"] = [_file("f2", drive_id="d2"), _file("f3", drive_id="d2")]

    estimate = _estimate(
        tenant, _scope(include_shared_drives=True, drives={"d1": ADMIN, "d2": BOB})
    )

    assert estimate.total_docs == 3
    assert estimate.partial is False
    assert {
        (call["drive_id"], call["user_email"])
        for call in tenant.calls
        if call["variant"] is DriveCorpus.DRIVE
    } == {("d1", ADMIN), ("d2", BOB)}


def test_a_reader_listed_drive_is_a_lower_bound_and_its_shared_copies_count_once() -> (
    None
):
    tenant = _Tenant()
    tenant.drives["d1"] = [_file("f1", drive_id="d1")]
    other = "someone@other.com"
    tenant.visible[ALICE] = [
        _file("f1", owner=other, drive_id="d1"),
        _file("f9", owner=other, drive_id="d1"),
    ]

    estimate = _estimate(
        tenant,
        _scope(
            include_shared_drives=True,
            include_files_shared_with_me=True,
            drives={"d1": ADMIN},
            incomplete_drive_ids=["d1"],
            my_drive_emails=[ALICE],
        ),
    )

    assert estimate.total_docs == 2
    assert estimate.partial is True
    assert estimate.detail is not None
    assert "shared drive d1 (listed as a reader" in estimate.detail


def test_what_nobody_can_list_is_reported_not_counted() -> None:
    tenant = _Tenant()
    tenant.drives["d1"] = [_file("f1", drive_id="d1")]
    tenant.broken_users.add(BOB)
    tenant.owned[ALICE] = [_file("a1")]

    estimate = _estimate(
        tenant,
        _scope(
            include_shared_drives=True,
            include_my_drives=True,
            drives={"d1": ADMIN},
            unlistable_drive_ids=["d2"],
            my_drive_emails=[ADMIN, ALICE, BOB],
        ),
    )

    assert estimate.total_docs == 2
    assert estimate.partial is True
    assert estimate.detail is not None
    assert "shared drive d2 (no user can list it)" in estimate.detail
    assert f"My Drive of {BOB}" in estimate.detail


def test_a_stop_ends_the_count_with_a_lower_bound() -> None:
    tenant = _Tenant()
    tenant.drives["d1"] = [_file("f1", drive_id="d1")]
    tenant.drives["d2"] = [_file("f2", drive_id="d2")]
    tenant.drives["d3"] = [_file("f3", drive_id="d3")]

    estimate = _estimate(
        tenant,
        _scope(
            include_shared_drives=True, drives={"d1": ADMIN, "d2": ADMIN, "d3": ADMIN}
        ),
        should_stop=lambda: True,
    )

    assert estimate.partial is True
    assert estimate.total_docs == 0
    assert estimate.detail == "stopped before the whole scope was counted"


def test_the_running_total_is_reported_while_the_count_goes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(corpus_estimate, "PROGRESS_INTERVAL_SECONDS", 0.0)
    tenant = _Tenant()
    tenant.owned[ALICE] = [_file("a1"), _file("a2", "application/pdf")]
    reports: list[CorpusEstimate] = []

    estimate = _estimate(
        tenant, _scope(my_drive_emails=[ALICE]), on_progress=reports.append
    )

    assert [report.total_docs for report in reports] == [1, 2]
    assert all(report.partial for report in reports)
    assert reports[-1].docs_by_type == {
        DocumentTypeLabel.DOCUMENT: 1,
        DocumentTypeLabel.PDF: 1,
    }
    assert estimate.total_docs == 2
    assert estimate.partial is False


def test_a_big_partition_is_split_by_modified_time_and_counted_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(corpus_estimate, "COUNT_PAGE_SIZE", 2)
    tenant = _Tenant()
    # Nine files across six timestamps, three of them sharing one.
    stamps = [
        "2024-01-01T00:00:00+00:00",
        "2024-02-01T00:00:00+00:00",
        "2024-03-01T00:00:00+00:00",
        "2024-03-01T00:00:00+00:00",
        "2024-03-01T00:00:00+00:00",
        "2024-04-01T00:00:00+00:00",
        "2024-05-01T00:00:00+00:00",
        "2024-06-01T00:00:00+00:00",
        "2024-07-01T00:00:00+00:00",
    ]
    tenant.drives["d1"] = [
        _file(f"f{i}", drive_id="d1", modified=stamp) for i, stamp in enumerate(stamps)
    ]

    estimate = _estimate(
        tenant, _scope(include_shared_drives=True, drives={"d1": ADMIN})
    )

    assert estimate.total_docs == 9
    assert estimate.partial is False
    # The drive was listed in more than one shard, never only serially, and
    # the shards end at the newest file rather than at the open window end.
    ascending = [c for c in tenant.calls if c["order_by"] == "modifiedTime"]
    assert len({call["query"] for call in ascending}) > 1
    upper_bounds = {
        bound
        for call in ascending
        for bound in re.findall(r"modifiedTime < '([^']+)'", call["query"])
    }
    assert max(upper_bounds) == "2024-07-01T00:00:00.001+00:00"


def test_a_requested_folder_is_sharded_and_its_subfolders_counted_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(corpus_estimate, "COUNT_PAGE_SIZE", 2)
    tenant = _Tenant()
    tenant.folders["top"] = [
        _file(f"t{i}", modified=f"2024-0{i}-01T00:00:00+00:00") for i in range(1, 6)
    ]
    # The subfolder is reachable from the top folder and requested on its own.
    tenant.subfolders["top"] = [{"id": "sub", "mimeType": DRIVE_FOLDER_TYPE}]
    tenant.folders["sub"] = [_file("s1"), _file("s2")]

    estimate = _estimate(tenant, _scope(folders={"top": [ADMIN], "sub": [ADMIN]}))

    assert estimate.total_docs == 7
    assert estimate.partial is False
    top_listings = {
        call["query"]
        for call in tenant.calls
        if "'top' in parents" in call["query"]
        and call.get("order_by") == "modifiedTime"
    }
    assert len(top_listings) > 1


def test_a_shortcut_counts_as_its_target_once_and_not_when_the_target_is_listed() -> (
    None
):
    tenant = _Tenant()
    tenant.drives["d1"] = [
        _file("f1", drive_id="d1"),
        _shortcut("s1", "f1", GDriveMimeType.DOC.value),
        _shortcut("s2", "elsewhere", "application/pdf"),
        _shortcut("s3", "elsewhere", "application/pdf"),
        _shortcut("s4", "unseen", "application/pdf"),
    ]
    tenant.targets["f1"] = _file("f1", drive_id="d1")
    tenant.targets["elsewhere"] = _file(
        "elsewhere", "application/pdf", owner="someone@other.com"
    )

    estimate = _estimate(
        tenant, _scope(include_shared_drives=True, drives={"d1": ADMIN})
    )

    assert estimate.docs_by_type == {
        DocumentTypeLabel.DOCUMENT: 1,
        DocumentTypeLabel.PDF: 1,
    }


def test_the_window_end_is_inclusive_like_the_run() -> None:
    tenant = _Tenant()
    stamp = "2024-06-01T00:00:00+00:00"
    tenant.drives["d1"] = [_file("f1", drive_id="d1", modified=stamp)]

    estimate = _estimate(
        tenant, _scope(include_shared_drives=True, drives={"d1": ADMIN}), end=_ts(stamp)
    )

    assert estimate.total_docs == 1


def test_a_stop_is_checked_before_requests_not_only_per_file() -> None:
    tenant = _Tenant()
    tenant.subfolders["top"] = [{"id": "sub", "mimeType": DRIVE_FOLDER_TYPE}]

    estimate = _estimate(
        tenant, _scope(folders={"top": [ADMIN]}), should_stop=lambda: True
    )

    assert estimate.partial is True
    assert estimate.total_docs == 0


def test_a_user_without_drive_access_is_skipped_not_fatal() -> None:
    tenant = _Tenant()
    tenant.no_drive_users.add(ALICE)
    tenant.owned[BOB] = [_file("b1", owner=BOB)]

    estimate = _estimate(
        tenant, _scope(include_my_drives=True, my_drive_emails=[ALICE, BOB])
    )

    assert estimate.total_docs == 1
    assert estimate.detail == f"My Drive of {ALICE} (no Drive access)"


def test_files_of_a_user_who_cannot_be_impersonated_count_through_another() -> None:
    tenant = _Tenant()
    tenant.broken_users.add(ALICE)
    tenant.owned[ALICE] = [_file("a1")]
    tenant.visible[BOB] = [_file("a1")]

    estimate = _estimate(
        tenant,
        _scope(
            include_my_drives=True,
            include_files_shared_with_me=True,
            my_drive_emails=[ALICE, BOB],
        ),
    )

    assert estimate.total_docs == 1
    assert estimate.partial is True


def test_a_partition_whose_first_page_is_empty_is_still_counted() -> None:
    tenant = _Tenant()
    tenant.leading_empty_page = True
    tenant.drives["d1"] = [_file("f1", drive_id="d1"), _file("f2", drive_id="d1")]

    estimate = _estimate(
        tenant, _scope(include_shared_drives=True, drives={"d1": ADMIN})
    )

    assert estimate.total_docs == 2
    assert estimate.partial is False


def test_a_shortcut_to_a_sized_file_counts_the_target_bytes() -> None:
    tenant = _Tenant()
    tenant.drives["d1"] = [_shortcut("s1", "big", "application/pdf")]
    tenant.targets["big"] = {**_file("big", "application/pdf"), "size": "500"}

    estimate = _estimate(
        tenant, _scope(include_shared_drives=True, drives={"d1": ADMIN})
    )

    assert estimate.bytes_by_type == {DocumentTypeLabel.PDF: 500}


def test_a_requested_folder_no_user_can_see_is_reported() -> None:
    tenant = _Tenant()

    estimate = _estimate(tenant, _scope(unreachable_folder_ids=["gone"]))

    assert estimate.total_docs == 0
    assert estimate.detail == "folder gone (no user can see it)"


def test_files_inside_one_second_are_paged_serially_and_counted_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(corpus_estimate, "COUNT_PAGE_SIZE", 2)
    tenant = _Tenant()
    tenant.drives["d1"] = [
        _file(f"f{i}", drive_id="d1", modified=f"2024-03-01T00:00:00.{i:03d}+00:00")
        for i in range(9)
    ]

    estimate = _estimate(
        tenant, _scope(include_shared_drives=True, drives={"d1": ADMIN})
    )

    assert estimate.total_docs == 9
    ascending = [c for c in tenant.calls if c["order_by"] == "modifiedTime"]
    assert len({call["query"] for call in ascending}) == 1


def test_a_restarted_page_does_not_count_its_rows_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(corpus_estimate, "COUNT_PAGE_SIZE", 2)
    tenant = _Tenant()
    tenant.restart_once = True
    tenant.drives["d1"] = [
        _file(f"f{i}", drive_id="d1", modified=f"2024-03-01T00:00:00.{i:03d}+00:00")
        for i in range(5)
    ]

    estimate = _estimate(
        tenant, _scope(include_shared_drives=True, drives={"d1": ADMIN})
    )

    assert estimate.total_docs == 5


def test_a_requested_folder_inside_a_listed_my_drive_counts_once() -> None:
    tenant = _Tenant()
    tenant.owned[ALICE] = [_file("a1")]
    tenant.folders["top"] = [_file("a1")]

    estimate = _estimate(
        tenant,
        _scope(
            include_my_drives=True, my_drive_emails=[ALICE], folders={"top": [ALICE]}
        ),
    )

    assert estimate.total_docs == 1
    assert estimate.partial is False


def test_an_oauth_listing_and_the_drives_it_reaches_count_once() -> None:
    tenant = _Tenant()
    other = "someone@other.com"
    tenant.drives["d1"] = [_file("f1", owner=other, drive_id="d1")]
    tenant.visible[ADMIN] = [
        _file("f1", owner=other, drive_id="d1"),
        _file("x1", "application/pdf", owner=other),
    ]

    estimate = _estimate(
        tenant,
        _scope(
            include_shared_drives=True,
            include_files_shared_with_me=True,
            drives={"d1": ADMIN},
        ),
        is_service_account=False,
    )

    assert estimate.total_docs == 2
    assert estimate.partial is False


def test_a_stop_during_planning_reports_a_stopped_empty_estimate() -> None:
    tenant = _Tenant()

    def plan() -> DriveCountScope:
        raise CountStopped()

    estimate = estimate_drive_corpus(
        tenant.ops,
        primary_admin_email=ADMIN,
        is_service_account=True,
        plan_scope=plan,
        start=None,
        end=None,
        should_stop=lambda: False,
        on_progress=lambda _: None,
    )

    assert estimate.total_docs == 0
    assert estimate.partial is True
    assert estimate.detail == "stopped before the whole scope was counted"
    assert not tenant.calls


def test_an_oauth_listing_counts_a_shortcut_to_a_file_it_lists_once() -> None:
    tenant = _Tenant()
    tenant.visible[ADMIN] = [
        _file("f1", owner=ADMIN),
        _shortcut("s1", "f1", GDriveMimeType.DOC.value),
        _shortcut("s2", "outside", "application/pdf"),
    ]
    tenant.targets["f1"] = _file("f1", owner=ADMIN)
    tenant.targets["outside"] = _file("outside", "application/pdf", drive_id="far")

    estimate = _estimate(
        tenant,
        _scope(include_my_drives=True, include_files_shared_with_me=True),
        is_service_account=False,
    )

    assert estimate.docs_by_type == {
        DocumentTypeLabel.DOCUMENT: 1,
        DocumentTypeLabel.PDF: 1,
    }
