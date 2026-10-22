"""Tests for per-page delta checkpointing in the SharePoint connector (P1-1).

Validates that:
- Delta drives process one page per _load_from_checkpoint call
- Checkpoints persist the delta next_link for resumption
- Crash + resume skips already-processed pages
- BFS (folder-scoped) drives process all items in one call
- 410 Gone triggers a full-resync URL in the checkpoint
- Duplicate document IDs across delta pages are deduplicated
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from typing import Any

import pytest

from onyx.connectors.microsoft_utils.drive_delta import (
    DriveDeltaFetchResult,
    DriveDeltaPage,
)
from onyx.connectors.microsoft_utils.drive_items import DriveFolderReference
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentSource,
    TextSection,
)
from onyx.connectors.sharepoint.connector import (
    DriveItemData,
    SharepointConnector,
    SharepointConnectorCheckpoint,
    SiteDescriptor,
    SiteDrive,
)
from onyx.connectors.sharepoint.models import SharepointDrive
from onyx.connectors.sharepoint.source_operations import (
    SharepointSourceOperations,
)
from tests.unit.onyx.connectors.sharepoint.sharepoint_gateway_fakes import (
    connector_with_gateway,
    stub_operation,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SITE_URL = "https://example.sharepoint.com/sites/sample"
DRIVE_WEB_URL = f"{SITE_URL}/Shared Documents"
DRIVE_ID = "fake-drive-id"
LIST_ID = "fake-list-id"

# Use a start time in the future so delta URLs include a timestamp token
_START_TS = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
_END_TS = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()

# For BFS tests we use epoch so no token is generated
_EPOCH_START: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(item_id: str, name: str = "doc.pdf") -> DriveItemData:
    return DriveItemData(
        id=item_id,
        name=name,
        web_url=f"{SITE_URL}/{name}",
        parent_reference_path="/drives/d1/root:",
        drive_id=DRIVE_ID,
    )


def _make_document(item: DriveItemData) -> Document:
    return Document(
        id=item.id,
        source=DocumentSource.SHAREPOINT,
        semantic_identifier=item.name,
        metadata={},
        sections=[TextSection(link=item.web_url, text="content")],
    )


def _delta_result(
    items: list[DriveItemData],
    next_url: str | None,
    *,
    resync_after_410: bool = False,
) -> DriveDeltaFetchResult:
    page = DriveDeltaPage.model_validate(
        {
            "value": [
                {
                    "id": item.id,
                    "name": item.name,
                    "webUrl": item.web_url,
                    "parentReference": {
                        "driveId": item.drive_id,
                        "path": item.parent_reference_path,
                    },
                }
                for item in items
            ]
        }
    )
    return DriveDeltaFetchResult(
        page=page,
        next_checkpoint_url=next_url,
        resync_after_410=resync_after_410,
    )


def _patch_delta_fetch(
    connector: SharepointConnector,
    fetch_page: Callable[..., tuple[list[DriveItemData], str | None]],
) -> None:
    """Stubs the gateway's delta page read with a ``(client, page_url,
    drive_id)`` style fake that answers items and the next URL."""

    def typed_fetch(
        *,
        drive_id: str,
        page_url: str,
        allow_full_resync: bool,  # noqa: ARG001
    ) -> DriveDeltaFetchResult:
        items, next_url = fetch_page(None, page_url, drive_id)
        return _delta_result(items, next_url)

    stub_operation(connector.ops, "get_delta_page", typed_fetch)


def _consume_generator(
    gen: Generator[Any, None, SharepointConnectorCheckpoint],
) -> tuple[list[Any], SharepointConnectorCheckpoint]:
    """Exhaust a _load_from_checkpoint generator.

    Returns (yielded_items, returned_checkpoint).
    """
    yielded: list[Any] = []
    try:
        while True:
            yielded.append(next(gen))
    except StopIteration as e:
        return yielded, e.value


def _docs_from(yielded: list[Any]) -> list[Document]:
    return [y for y in yielded if isinstance(y, Document)]


def _failures_from(yielded: list[Any]) -> list[ConnectorFailure]:
    return [y for y in yielded if isinstance(y, ConnectorFailure)]


def _build_ready_checkpoint(
    drive_names: list[str] | None = None,
    folder_path: str | None = None,
) -> SharepointConnectorCheckpoint:
    """Checkpoint ready for Phase 3 (sites initialised, drives queued)."""
    cp = SharepointConnectorCheckpoint(has_more=True)
    cp.cached_site_descriptors = deque()
    cp.current_site_descriptor = SiteDescriptor(
        url=SITE_URL,
        drive_name=None,
        folder_path=folder_path,
    )
    cp.cached_drives = deque(
        SiteDrive(
            drive_id=f"{DRIVE_ID}-{name}",
            list_id=f"{LIST_ID}-{name}",
            display_name=name,
            web_url=f"{SITE_URL}/{name}",
        )
        for name in (drive_names or ["Documents"])
    )
    cp.process_site_pages = False
    return cp


def _setup_connector() -> SharepointConnector:
    """A connector over a fake gateway whose folder resolution is stubbed."""
    connector = SharepointConnector()
    connector_with_gateway(connector)
    connector.include_site_pages = False
    stub_operation(
        connector.ops,
        "resolve_folder",
        lambda *, drive_id, folder_path: DriveFolderReference(  # noqa: ARG005
            id="folder-id", web_url=f"{DRIVE_WEB_URL}/Engineering/Docs"
        ),
    )
    return connector


def _mock_convert(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace _convert_driveitem_to_document_with_permissions with a trivial stub."""

    def fake_convert(
        driveitem: DriveItemData,
        drive: SiteDrive,  # noqa: ARG001
        ops: SharepointSourceOperations,  # noqa: ARG001
        site_url: str,  # noqa: ARG001
        include_permissions: bool = False,  # noqa: ARG001
        parent_hierarchy_raw_node_id: str | None = None,  # noqa: ARG001
        treat_sharing_link_as_public: bool = False,  # noqa: ARG001
        raw_file_callback: Any = None,  # noqa: ARG001
        permission_cache: Any = None,  # noqa: ARG001
    ) -> Document:
        return _make_document(driveitem)

    monkeypatch.setattr(
        "onyx.connectors.sharepoint.connector._convert_driveitem_to_document_with_permissions",
        fake_convert,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDeltaPerPageCheckpointing:
    """Delta (non-folder-scoped) drives should process one API page per
    _load_from_checkpoint call, persisting the next-link in between."""

    def test_processes_one_page_per_cycle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        items_p1 = [_make_item("a"), _make_item("b")]
        items_p2 = [_make_item("c")]
        items_p3 = [_make_item("d"), _make_item("e")]

        call_count = 0

        def fake_fetch_page(
            client: Any,  # noqa: ARG001
            page_url: str,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> tuple[list[DriveItemData], str | None]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return items_p1, "https://graph.microsoft.com/next2"
            if call_count == 2:
                return items_p2, "https://graph.microsoft.com/next3"
            return items_p3, None

        _patch_delta_fetch(connector, fake_fetch_page)

        checkpoint = _build_ready_checkpoint()

        # Call 1: Phase 3a inits drive, Phase 3b processes page 1
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, checkpoint = _consume_generator(gen)
        assert len(_docs_from(yielded)) == 2
        assert (
            checkpoint.current_drive_delta_next_link
            == "https://graph.microsoft.com/next2"
        )
        assert checkpoint.current_drive is not None
        assert checkpoint.current_drive.drive_id == f"{DRIVE_ID}-Documents"
        assert checkpoint.has_more is True

        # Call 2: Phase 3b processes page 2
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, checkpoint = _consume_generator(gen)
        assert len(_docs_from(yielded)) == 1
        assert (
            checkpoint.current_drive_delta_next_link
            == "https://graph.microsoft.com/next3"
        )

        # Call 3: Phase 3b processes page 3 (last)
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, checkpoint = _consume_generator(gen)
        assert len(_docs_from(yielded)) == 2
        assert checkpoint.current_drive is None
        assert checkpoint.current_drive_delta_next_link is None

    def test_resume_after_simulated_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Serialise the checkpoint after page 1, create a fresh connector,
        and verify page 2 is fetched using the saved next-link."""
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        captured_urls: list[str] = []
        call_count = 0

        def fake_fetch_page(
            client: Any,  # noqa: ARG001
            page_url: str,
            drive_id: str,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> tuple[list[DriveItemData], str | None]:
            nonlocal call_count
            call_count += 1
            captured_urls.append(page_url)
            if call_count == 1:
                return [_make_item("a")], "https://graph.microsoft.com/next2"
            return [_make_item("b")], None

        _patch_delta_fetch(connector, fake_fetch_page)

        # Process page 1
        checkpoint = _build_ready_checkpoint()
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        _, checkpoint = _consume_generator(gen)
        assert (
            checkpoint.current_drive_delta_next_link
            == "https://graph.microsoft.com/next2"
        )

        # --- Simulate crash: serialise & deserialise checkpoint ---
        saved_json = checkpoint.model_dump_json()
        restored = SharepointConnectorCheckpoint.model_validate_json(saved_json)

        # New connector instance (as if process restarted)
        connector2 = _setup_connector()
        _mock_convert(monkeypatch)
        _patch_delta_fetch(connector2, fake_fetch_page)

        # Resume — should pick up from next2
        gen = connector2._load_from_checkpoint(
            _START_TS, _END_TS, restored, include_permissions=False
        )
        yielded, final_cp = _consume_generator(gen)

        docs = _docs_from(yielded)
        assert len(docs) == 1
        assert docs[0].id == "b"
        assert captured_urls[-1] == "https://graph.microsoft.com/next2"
        assert final_cp.current_drive is None
        assert final_cp.current_drive_delta_next_link is None

    def test_legacy_checkpoint_resolves_drive_identity_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connector = _setup_connector()
        _mock_convert(monkeypatch)
        listed_site_urls: list[str] = []

        def fake_list_drives(*, site_url: str) -> list[SharepointDrive]:
            listed_site_urls.append(site_url)
            return [
                SharepointDrive(
                    id=DRIVE_ID,
                    name="OneDrive",
                    web_url=DRIVE_WEB_URL,
                    list_id=LIST_ID,
                )
            ]

        stub_operation(connector.ops, "list_drives", fake_list_drives)
        stub_operation(
            connector.ops,
            "get_delta_page",
            lambda **_kwargs: _delta_result([_make_item("resumed")], None),
        )
        legacy_json = json.dumps(
            {
                "has_more": True,
                "cached_site_descriptors": [],
                "current_site_descriptor": {
                    "url": SITE_URL,
                    "drive_name": "Documents",
                    "folder_path": None,
                },
                "cached_drive_names": [],
                "current_drive_name": "Documents",
                "current_drive_id": DRIVE_ID,
                "current_drive_web_url": "https://stale.example/Documents",
                "current_drive_delta_next_link": "https://graph.example/next",
            }
        )

        checkpoint = connector.validate_checkpoint_json(legacy_json)
        yielded, migrated = _consume_generator(
            connector._load_from_checkpoint(
                _START_TS, _END_TS, checkpoint, include_permissions=False
            )
        )

        assert [doc.id for doc in _docs_from(yielded)] == ["resumed"]
        assert listed_site_urls == [SITE_URL]
        assert migrated.current_drive is None
        dumped = migrated.model_dump()
        assert "cached_drive_names" not in dumped
        assert "current_drive_name" not in dumped

    def test_legacy_drive_listing_failure_propagates(self) -> None:
        connector = _setup_connector()

        def failing_list_drives(*, site_url: str) -> list[SharepointDrive]:  # noqa: ARG001
            raise RuntimeError("Graph unavailable")

        stub_operation(connector.ops, "list_drives", failing_list_drives)
        checkpoint = SharepointConnectorCheckpoint(
            has_more=True,
            cached_site_descriptors=deque(),
            current_site_descriptor=SiteDescriptor(
                url=SITE_URL,
                drive_name="Documents",
                folder_path=None,
            ),
            legacy_cached_drive_names=deque(),
            legacy_current_drive_name="Documents",
            legacy_current_drive_id=DRIVE_ID,
        )

        with pytest.raises(RuntimeError, match="Graph unavailable"):
            _consume_generator(
                connector._load_from_checkpoint(
                    _START_TS, _END_TS, checkpoint, include_permissions=False
                )
            )

    def test_single_page_drive_completes_in_one_cycle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A drive with only one delta page should init + process + clear
        in a single _load_from_checkpoint call."""
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        def fake_fetch_page(
            client: Any,  # noqa: ARG001
            page_url: str,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> tuple[list[DriveItemData], str | None]:
            return [_make_item("only")], None

        _patch_delta_fetch(connector, fake_fetch_page)

        checkpoint = _build_ready_checkpoint()
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, final_cp = _consume_generator(gen)

        assert len(_docs_from(yielded)) == 1
        assert final_cp.current_drive is None
        assert final_cp.current_drive_delta_next_link is None


class TestBfsPathNoCheckpointing:
    """Folder-scoped (BFS) drives should process all items in one call
    because the BFS queue cannot be cheaply serialised."""

    def test_bfs_processes_all_at_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        items = [_make_item("x"), _make_item("y"), _make_item("z")]

        def fake_iter_paged(
            *,
            drive_id: str,  # noqa: ARG001
            folder_id: str | None,  # noqa: ARG001
            start: datetime | None,  # noqa: ARG001
            end: datetime | None,  # noqa: ARG001
        ) -> Generator[DriveItemData, None, None]:
            yield from items

        stub_operation(connector.ops, "iter_folder_items", fake_iter_paged)

        checkpoint = _build_ready_checkpoint(folder_path="Engineering/Docs")
        gen = connector._load_from_checkpoint(
            _EPOCH_START, _END_TS, checkpoint, include_permissions=False
        )
        yielded, final_cp = _consume_generator(gen)

        assert len(_docs_from(yielded)) == 3
        assert final_cp.current_drive is None
        assert final_cp.current_drive_delta_next_link is None

    def test_bfs_resume_uses_checkpointed_folder_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connector = _setup_connector()
        _mock_convert(monkeypatch)
        folder_ids: list[str | None] = []

        def fake_iter_paged(
            *,
            drive_id: str,  # noqa: ARG001
            folder_id: str | None,
            start: datetime | None,  # noqa: ARG001
            end: datetime | None,  # noqa: ARG001
        ) -> Generator[DriveItemData, None, None]:
            folder_ids.append(folder_id)
            yield _make_item("resumed")

        stub_operation(connector.ops, "iter_folder_items", fake_iter_paged)
        stub_operation(
            connector.ops,
            "resolve_folder",
            lambda **_kwargs: pytest.fail("folder path was resolved again"),
        )
        checkpoint = _build_ready_checkpoint(folder_path="Engineering/Docs")
        assert checkpoint.cached_drives is not None
        checkpoint.current_drive = checkpoint.cached_drives.popleft()
        checkpoint.current_folder = DriveFolderReference(
            id="saved-folder-id", web_url=f"{DRIVE_WEB_URL}/Engineering/Docs"
        )

        yielded, _ = _consume_generator(
            connector._load_from_checkpoint(
                _EPOCH_START, _END_TS, checkpoint, include_permissions=False
            )
        )

        assert [doc.id for doc in _docs_from(yielded)] == ["resumed"]
        assert folder_ids == ["saved-folder-id"]


class TestDelta410GoneResync:
    """A drive can enter full resync at most once."""

    def test_resync_bound_survives_resume_and_repeated_410_progresses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        def fake_fetch_page(
            *,
            drive_id: str,
            page_url: str,  # noqa: ARG001
            allow_full_resync: bool,
        ) -> DriveDeltaFetchResult:
            allow_attempts.append(allow_full_resync)
            full_url = (
                f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/delta"
                "?$top=200"
            )
            if len(allow_attempts) <= 2:
                return _delta_result([], full_url, resync_after_410=True)
            if len(allow_attempts) == 3:
                return _delta_result([_make_item("recovered")], f"{full_url}&page=2")
            if len(allow_attempts) == 4:
                raise MicrosoftGraphError(410, "resyncRequired", "gone")
            return _delta_result([], None)

        allow_attempts: list[bool] = []
        stub_operation(connector.ops, "get_delta_page", fake_fetch_page)
        checkpoint = _build_ready_checkpoint(["Documents", "Second"])
        stale_checkpoint_json = checkpoint.model_dump_json()

        _, checkpoint = _consume_generator(
            connector._load_from_checkpoint(
                _START_TS, _END_TS, checkpoint, include_permissions=False
            )
        )
        assert checkpoint.current_drive_delta_resync_attempted
        assert checkpoint.current_drive_delta_next_link is not None
        assert "token=" not in checkpoint.current_drive_delta_next_link

        stale_checkpoint = SharepointConnectorCheckpoint.model_validate_json(
            stale_checkpoint_json
        )
        _, stale_checkpoint = _consume_generator(
            connector._load_from_checkpoint(
                _START_TS, _END_TS, stale_checkpoint, include_permissions=False
            )
        )
        assert stale_checkpoint.current_drive_delta_resync_attempted

        checkpoint = SharepointConnectorCheckpoint.model_validate_json(
            checkpoint.model_dump_json()
        )
        yielded, checkpoint = _consume_generator(
            connector._load_from_checkpoint(
                _START_TS, _END_TS, checkpoint, include_permissions=False
            )
        )
        assert [document.id for document in _docs_from(yielded)] == ["recovered"]
        assert checkpoint.current_drive_delta_resync_attempted

        yielded, checkpoint = _consume_generator(
            connector._load_from_checkpoint(
                _START_TS, _END_TS, checkpoint, include_permissions=False
            )
        )
        assert len(_failures_from(yielded)) == 1
        assert checkpoint.current_drive is None
        assert not checkpoint.current_drive_delta_resync_attempted

        _, checkpoint = _consume_generator(
            connector._load_from_checkpoint(
                _START_TS, _END_TS, checkpoint, include_permissions=False
            )
        )
        assert checkpoint.current_drive is None
        assert allow_attempts == [True, True, False, False, True]


class TestDeltaPageFetchFailure:
    """If a delta page fetch fails, the drive should be abandoned with a
    ConnectorFailure and the checkpoint should be cleared for the next drive."""

    def test_page_fetch_error_yields_failure_and_clears_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        def fake_fetch_page(
            client: Any,  # noqa: ARG001
            page_url: str,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> tuple[list[DriveItemData], str | None]:
            raise RuntimeError("network blip")

        _patch_delta_fetch(connector, fake_fetch_page)

        checkpoint = _build_ready_checkpoint()
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, final_cp = _consume_generator(gen)

        failures = _failures_from(yielded)
        assert len(failures) == 1
        assert "network blip" in failures[0].failure_message
        assert final_cp.current_drive is None
        assert final_cp.current_drive_delta_next_link is None


class TestDeltaDuplicateDocumentDedup:
    """The Microsoft Graph delta API can return the same item on multiple
    pages.  Documents already yielded should be skipped via
    checkpoint.seen_document_ids."""

    def test_duplicate_across_pages_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Item 'dup' appears on both page 1 and page 2.  It should only be
        yielded once."""
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        call_count = 0

        def fake_fetch_page(
            client: Any,  # noqa: ARG001
            page_url: str,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> tuple[list[DriveItemData], str | None]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [_make_item("a"), _make_item("dup")], "https://next2"
            return [_make_item("dup"), _make_item("b")], None

        _patch_delta_fetch(connector, fake_fetch_page)

        checkpoint = _build_ready_checkpoint()

        # Page 1: yields a, dup
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, checkpoint = _consume_generator(gen)
        docs = _docs_from(yielded)
        assert [d.id for d in docs] == ["a", "dup"]
        assert "dup" in checkpoint.seen_document_ids

        # Page 2: dup should be skipped, only b yielded
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, checkpoint = _consume_generator(gen)
        docs = _docs_from(yielded)
        assert [d.id for d in docs] == ["b"]

    def test_duplicate_within_same_page_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the same item appears twice on a single delta page, only the
        first occurrence should be yielded."""
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        def fake_fetch_page(
            client: Any,  # noqa: ARG001
            page_url: str,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> tuple[list[DriveItemData], str | None]:
            return [_make_item("x"), _make_item("x"), _make_item("y")], None

        _patch_delta_fetch(connector, fake_fetch_page)

        checkpoint = _build_ready_checkpoint()
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, checkpoint = _consume_generator(gen)
        docs = _docs_from(yielded)
        assert [d.id for d in docs] == ["x", "y"]

    def test_seen_ids_survive_checkpoint_serialization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """seen_document_ids must survive JSON serialization so that
        dedup works across crash + resume."""
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        call_count = 0

        def fake_fetch_page(
            client: Any,  # noqa: ARG001
            page_url: str,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> tuple[list[DriveItemData], str | None]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [_make_item("a")], "https://next2"
            return [_make_item("a"), _make_item("b")], None

        _patch_delta_fetch(connector, fake_fetch_page)

        checkpoint = _build_ready_checkpoint()

        # Page 1
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        _, checkpoint = _consume_generator(gen)
        assert "a" in checkpoint.seen_document_ids

        # Simulate crash: round-trip through JSON
        restored = SharepointConnectorCheckpoint.model_validate_json(
            checkpoint.model_dump_json()
        )
        assert "a" in restored.seen_document_ids

        # Page 2 with restored checkpoint: 'a' should be skipped
        connector2 = _setup_connector()
        _mock_convert(monkeypatch)
        _patch_delta_fetch(connector2, fake_fetch_page)

        gen = connector2._load_from_checkpoint(
            _START_TS, _END_TS, restored, include_permissions=False
        )
        yielded, final_cp = _consume_generator(gen)
        docs = _docs_from(yielded)
        assert [d.id for d in docs] == ["b"]

    def test_no_dedup_across_separate_indexing_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fresh checkpoint (new indexing run) should have an empty
        seen_document_ids, so previously-indexed docs are re-processed."""
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        def fake_fetch_page(
            client: Any,  # noqa: ARG001
            page_url: str,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> tuple[list[DriveItemData], str | None]:
            return [_make_item("a")], None

        _patch_delta_fetch(connector, fake_fetch_page)

        # First run
        cp1 = _build_ready_checkpoint()
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, cp1, include_permissions=False
        )
        yielded, _ = _consume_generator(gen)
        assert len(_docs_from(yielded)) == 1

        # Second run with a fresh checkpoint — same doc should appear again
        cp2 = _build_ready_checkpoint()
        assert len(cp2.seen_document_ids) == 0
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, cp2, include_permissions=False
        )
        yielded, _ = _consume_generator(gen)
        assert len(_docs_from(yielded)) == 1

    def test_same_id_across_drives_not_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Graph item IDs are only unique within a drive.  An item in drive B
        that happens to share an ID with an item already seen in drive A must
        NOT be skipped."""
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        def fake_fetch_page(
            client: Any,  # noqa: ARG001
            page_url: str,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> tuple[list[DriveItemData], str | None]:
            return [_make_item("shared-id")], None

        _patch_delta_fetch(connector, fake_fetch_page)

        checkpoint = _build_ready_checkpoint(drive_names=["DriveA", "DriveB"])

        # Drive A: yields the item
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, checkpoint = _consume_generator(gen)
        docs = _docs_from(yielded)
        assert len(docs) == 1
        assert docs[0].id == "shared-id"

        # seen_document_ids should have been cleared when drive A finished
        assert len(checkpoint.seen_document_ids) == 0

        # Drive B: same ID must be yielded again (different drive)
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, checkpoint = _consume_generator(gen)
        docs = _docs_from(yielded)
        assert len(docs) == 1
        assert docs[0].id == "shared-id"
