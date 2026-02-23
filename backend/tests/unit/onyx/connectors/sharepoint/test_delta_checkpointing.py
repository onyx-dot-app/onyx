"""Tests for per-page delta checkpointing in the SharePoint connector (P1-1).

Validates that:
- Delta drives process one page per _load_from_checkpoint call
- Checkpoints persist the delta next_link for resumption
- Crash + resume skips already-processed pages
- BFS (folder-scoped) drives process all items in one call
- 410 Gone triggers a full-resync URL in the checkpoint
"""

from __future__ import annotations

from collections import deque
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any

import pytest

from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import TextSection
from onyx.connectors.sharepoint.connector import DriveItemData
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.sharepoint.connector import SharepointConnectorCheckpoint
from onyx.connectors.sharepoint.connector import SiteDescriptor

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SITE_URL = "https://example.sharepoint.com/sites/sample"
DRIVE_WEB_URL = f"{SITE_URL}/Shared Documents"
DRIVE_ID = "fake-drive-id"

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
    cp.cached_drive_names = deque(drive_names or ["Documents"])
    cp.process_site_pages = False
    return cp


def _setup_connector(monkeypatch: pytest.MonkeyPatch) -> SharepointConnector:
    """Create a connector with common methods mocked."""
    connector = SharepointConnector()
    connector._graph_client = object()
    connector.include_site_pages = False

    def fake_resolve_drive(
        self: SharepointConnector,  # noqa: ARG001
        site_descriptor: SiteDescriptor,  # noqa: ARG001
        drive_name: str,  # noqa: ARG001
    ) -> tuple[str, str | None]:
        return (DRIVE_ID, DRIVE_WEB_URL)

    def fake_get_access_token(self: SharepointConnector) -> str:  # noqa: ARG001
        return "fake-access-token"

    monkeypatch.setattr(SharepointConnector, "_resolve_drive", fake_resolve_drive)
    monkeypatch.setattr(
        SharepointConnector, "_get_graph_access_token", fake_get_access_token
    )

    return connector


def _mock_convert(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace _convert_driveitem_to_document_with_permissions with a trivial stub."""

    def fake_convert(
        driveitem: DriveItemData,
        drive_name: str,  # noqa: ARG001
        ctx: Any = None,  # noqa: ARG001
        graph_client: Any = None,  # noqa: ARG001
        graph_api_base: str = "",  # noqa: ARG001
        include_permissions: bool = False,  # noqa: ARG001
        parent_hierarchy_raw_node_id: str | None = None,  # noqa: ARG001
        access_token: str | None = None,  # noqa: ARG001
    ) -> Document:
        return _make_document(driveitem)

    monkeypatch.setattr(
        "onyx.connectors.sharepoint.connector"
        "._convert_driveitem_to_document_with_permissions",
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
        connector = _setup_connector(monkeypatch)
        _mock_convert(monkeypatch)

        items_p1 = [_make_item("a"), _make_item("b")]
        items_p2 = [_make_item("c")]
        items_p3 = [_make_item("d"), _make_item("e")]

        call_count = 0

        def fake_fetch_page(
            self: SharepointConnector,  # noqa: ARG001
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

        monkeypatch.setattr(
            SharepointConnector, "_fetch_one_delta_page", fake_fetch_page
        )

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
        assert checkpoint.current_drive_id == DRIVE_ID
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
        assert checkpoint.current_drive_name is None
        assert checkpoint.current_drive_id is None
        assert checkpoint.current_drive_delta_next_link is None

    def test_resume_after_simulated_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Serialise the checkpoint after page 1, create a fresh connector,
        and verify page 2 is fetched using the saved next-link."""
        connector = _setup_connector(monkeypatch)
        _mock_convert(monkeypatch)

        captured_urls: list[str] = []
        call_count = 0

        def fake_fetch_page(
            self: SharepointConnector,  # noqa: ARG001
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

        monkeypatch.setattr(
            SharepointConnector, "_fetch_one_delta_page", fake_fetch_page
        )

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
        connector2 = _setup_connector(monkeypatch)
        _mock_convert(monkeypatch)
        monkeypatch.setattr(
            SharepointConnector, "_fetch_one_delta_page", fake_fetch_page
        )

        # Resume — should pick up from next2
        gen = connector2._load_from_checkpoint(
            _START_TS, _END_TS, restored, include_permissions=False
        )
        yielded, final_cp = _consume_generator(gen)

        docs = _docs_from(yielded)
        assert len(docs) == 1
        assert docs[0].id == "b"
        assert captured_urls[-1] == "https://graph.microsoft.com/next2"
        assert final_cp.current_drive_name is None
        assert final_cp.current_drive_delta_next_link is None

    def test_single_page_drive_completes_in_one_cycle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A drive with only one delta page should init + process + clear
        in a single _load_from_checkpoint call."""
        connector = _setup_connector(monkeypatch)
        _mock_convert(monkeypatch)

        def fake_fetch_page(
            self: SharepointConnector,  # noqa: ARG001
            page_url: str,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> tuple[list[DriveItemData], str | None]:
            return [_make_item("only")], None

        monkeypatch.setattr(
            SharepointConnector, "_fetch_one_delta_page", fake_fetch_page
        )

        checkpoint = _build_ready_checkpoint()
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, final_cp = _consume_generator(gen)

        assert len(_docs_from(yielded)) == 1
        assert final_cp.current_drive_name is None
        assert final_cp.current_drive_id is None
        assert final_cp.current_drive_delta_next_link is None


class TestBfsPathNoCheckpointing:
    """Folder-scoped (BFS) drives should process all items in one call
    because the BFS queue cannot be cheaply serialised."""

    def test_bfs_processes_all_at_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        connector = _setup_connector(monkeypatch)
        _mock_convert(monkeypatch)

        items = [_make_item("x"), _make_item("y"), _make_item("z")]

        def fake_iter_paged(
            self: SharepointConnector,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            folder_path: str | None = None,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> Generator[DriveItemData, None, None]:
            yield from items

        monkeypatch.setattr(
            SharepointConnector, "_iter_drive_items_paged", fake_iter_paged
        )

        checkpoint = _build_ready_checkpoint(folder_path="Engineering/Docs")
        gen = connector._load_from_checkpoint(
            _EPOCH_START, _END_TS, checkpoint, include_permissions=False
        )
        yielded, final_cp = _consume_generator(gen)

        assert len(_docs_from(yielded)) == 3
        assert final_cp.current_drive_name is None
        assert final_cp.current_drive_id is None
        assert final_cp.current_drive_delta_next_link is None


class TestDelta410GoneResync:
    """On 410 Gone the checkpoint should be updated with a full-resync URL
    and the next cycle should re-enumerate from scratch."""

    def test_410_stores_full_resync_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        connector = _setup_connector(monkeypatch)
        _mock_convert(monkeypatch)

        call_count = 0

        def fake_fetch_page(
            self: SharepointConnector,  # noqa: ARG001
            page_url: str,  # noqa: ARG001
            drive_id: str,
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,
        ) -> tuple[list[DriveItemData], str | None]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Simulate the 410 handler returning a full-resync URL
                full_url = (
                    f"https://graph.microsoft.com/v1.0/drives/{drive_id}"
                    f"/root/delta?$top={page_size}"
                )
                return [], full_url
            return [_make_item("recovered")], None

        monkeypatch.setattr(
            SharepointConnector, "_fetch_one_delta_page", fake_fetch_page
        )

        checkpoint = _build_ready_checkpoint()

        # Call 1: 3a inits, 3b gets empty page + resync URL
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, checkpoint = _consume_generator(gen)
        assert len(_docs_from(yielded)) == 0
        assert checkpoint.current_drive_delta_next_link is not None
        assert "token=" not in checkpoint.current_drive_delta_next_link

        # Call 2: processes the full resync
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, checkpoint = _consume_generator(gen)
        docs = _docs_from(yielded)
        assert len(docs) == 1
        assert docs[0].id == "recovered"
        assert checkpoint.current_drive_name is None


class TestDeltaPageFetchFailure:
    """If _fetch_one_delta_page raises, the drive should be abandoned with a
    ConnectorFailure and the checkpoint should be cleared for the next drive."""

    def test_page_fetch_error_yields_failure_and_clears_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connector = _setup_connector(monkeypatch)
        _mock_convert(monkeypatch)

        def fake_fetch_page(
            self: SharepointConnector,  # noqa: ARG001
            page_url: str,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> tuple[list[DriveItemData], str | None]:
            raise RuntimeError("network blip")

        monkeypatch.setattr(
            SharepointConnector, "_fetch_one_delta_page", fake_fetch_page
        )

        checkpoint = _build_ready_checkpoint()
        gen = connector._load_from_checkpoint(
            _START_TS, _END_TS, checkpoint, include_permissions=False
        )
        yielded, final_cp = _consume_generator(gen)

        failures = _failures_from(yielded)
        assert len(failures) == 1
        assert "network blip" in failures[0].failure_message
        assert final_cp.current_drive_name is None
        assert final_cp.current_drive_id is None
        assert final_cp.current_drive_delta_next_link is None
