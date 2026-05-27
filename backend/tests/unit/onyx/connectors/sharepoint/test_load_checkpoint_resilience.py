"""Tests for resilience wrappers added to SharepointConnector._load_from_checkpoint.

Covers three failure modes that previously aborted the whole attempt:
- G1: BFS-mode generator (`_iter_drive_items_paged`) raising mid-iteration.
- G2: `_fetch_site_pages` raising a non-Graph 4xx in Phase 5.
- G3: A single site page failing to convert in Phase 5.

All three now yield a ConnectorFailure (EntityFailure or DocumentFailure)
and let the rest of the indexing run continue.
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
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import TextSection
from onyx.connectors.sharepoint.connector import DriveItemData
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.sharepoint.connector import SharepointConnectorCheckpoint
from onyx.connectors.sharepoint.connector import SiteDescriptor

SITE_URL = "https://example.sharepoint.com/sites/sample"
DRIVE_WEB_URL = f"{SITE_URL}/Shared Documents"
DRIVE_ID = "fake-drive-id"
# Use a name that isn't in SHARED_DOCUMENTS_MAP so the assertions can use it verbatim.
DRIVE_NAME = "Engineering"

_EPOCH_START: float = 0.0
_END_TS = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()


# ---------------------------------------------------------------------------
# Helpers (mirrors of test_delta_checkpointing.py; kept local so this file is
# self-contained).
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


def _setup_connector(monkeypatch: pytest.MonkeyPatch) -> SharepointConnector:
    connector = SharepointConnector()
    connector._graph_client = object()  # ty: ignore[invalid-assignment]
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
    def fake_convert(
        driveitem: DriveItemData,
        drive_name: str,  # noqa: ARG001
        ctx: Any = None,  # noqa: ARG001
        graph_client: Any = None,  # noqa: ARG001
        graph_api_base: str = "",  # noqa: ARG001
        include_permissions: bool = False,  # noqa: ARG001
        parent_hierarchy_raw_node_id: str | None = None,  # noqa: ARG001
        access_token: str | None = None,  # noqa: ARG001
        treat_sharing_link_as_public: bool = False,  # noqa: ARG001
        raw_file_callback: Any = None,  # noqa: ARG001
    ) -> Document:
        return _make_document(driveitem)

    monkeypatch.setattr(
        "onyx.connectors.sharepoint.connector._convert_driveitem_to_document_with_permissions",
        fake_convert,
    )


def _build_phase3_checkpoint(
    folder_path: str | None = None,
) -> SharepointConnectorCheckpoint:
    """Checkpoint ready to enter Phase 3 (site initialised, one drive queued)."""
    cp = SharepointConnectorCheckpoint(has_more=True)
    cp.cached_site_descriptors = deque()
    cp.current_site_descriptor = SiteDescriptor(
        url=SITE_URL, drive_name=None, folder_path=folder_path
    )
    cp.cached_drive_names = deque([DRIVE_NAME])
    cp.process_site_pages = False
    return cp


def _build_phase5_checkpoint() -> SharepointConnectorCheckpoint:
    """Checkpoint ready to enter Phase 5 directly (drives done, site pages flagged)."""
    cp = SharepointConnectorCheckpoint(has_more=True)
    cp.cached_site_descriptors = deque()
    cp.current_site_descriptor = SiteDescriptor(
        url=SITE_URL, drive_name=None, folder_path=None
    )
    cp.cached_drive_names = deque()
    cp.process_site_pages = True
    return cp


# ---------------------------------------------------------------------------
# G1 — BFS-mode generator failures mid-iteration
# ---------------------------------------------------------------------------


class TestBfsIterationFailure:
    """When `_iter_drive_items_paged` (BFS path) raises after yielding some
    items, items emitted before the raise are kept, an EntityFailure is
    yielded for the drive, the drive checkpoint state is cleared, and the
    generator returns cleanly instead of aborting the attempt."""

    def test_bfs_generator_failure_yields_entity_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connector = _setup_connector(monkeypatch)
        _mock_convert(monkeypatch)

        good_items = [_make_item("a"), _make_item("b")]

        def fake_iter_paged(
            self: SharepointConnector,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            folder_path: str | None = None,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> Generator[DriveItemData, None, None]:
            yield from good_items
            raise RuntimeError("graph 500 mid-page")

        monkeypatch.setattr(
            SharepointConnector, "_iter_drive_items_paged", fake_iter_paged
        )

        # folder_path forces BFS mode
        checkpoint = _build_phase3_checkpoint(folder_path="Engineering/Docs")
        gen = connector._load_from_checkpoint(
            _EPOCH_START, _END_TS, checkpoint, include_permissions=False
        )
        yielded, final_cp = _consume_generator(gen)

        docs = _docs_from(yielded)
        failures = _failures_from(yielded)

        assert [d.id for d in docs] == ["a", "b"]
        assert len(failures) == 1
        failed_entity = failures[0].failed_entity
        assert failed_entity is not None
        assert isinstance(failed_entity, EntityFailure)
        assert failed_entity.entity_id == f"{SITE_URL}|{DRIVE_NAME}|bfs_iter"
        assert "graph 500 mid-page" in failures[0].failure_message

        # Drive state cleared so resume doesn't loop on the broken drive.
        assert final_cp.current_drive_name is None
        assert final_cp.current_drive_id is None
        assert final_cp.current_drive_web_url is None
        assert final_cp.current_drive_delta_next_link is None

    def test_bfs_generator_failure_at_start_still_yields_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A raise before any item is yielded still produces an EntityFailure
        rather than crashing the attempt."""
        connector = _setup_connector(monkeypatch)
        _mock_convert(monkeypatch)

        def fake_iter_paged(
            self: SharepointConnector,  # noqa: ARG001
            drive_id: str,  # noqa: ARG001
            folder_path: str | None = None,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
            page_size: int = 200,  # noqa: ARG001
        ) -> Generator[DriveItemData, None, None]:
            raise RuntimeError("connection reset")
            yield  # pragma: no cover  # make this a generator

        monkeypatch.setattr(
            SharepointConnector, "_iter_drive_items_paged", fake_iter_paged
        )

        checkpoint = _build_phase3_checkpoint(folder_path="Engineering/Docs")
        gen = connector._load_from_checkpoint(
            _EPOCH_START, _END_TS, checkpoint, include_permissions=False
        )
        yielded, final_cp = _consume_generator(gen)

        assert _docs_from(yielded) == []
        failures = _failures_from(yielded)
        assert len(failures) == 1
        assert failures[0].failed_entity is not None
        assert (
            failures[0].failed_entity.entity_id == f"{SITE_URL}|{DRIVE_NAME}|bfs_iter"
        )
        assert final_cp.current_drive_name is None


# ---------------------------------------------------------------------------
# G2 + G3 — Phase 5 site-pages wrap
# ---------------------------------------------------------------------------


def _mock_convert_sitepage(
    monkeypatch: pytest.MonkeyPatch,
    side_effect: Any,
) -> None:
    monkeypatch.setattr(
        "onyx.connectors.sharepoint.connector._convert_sitepage_to_document",
        side_effect,
    )


class TestSitePagesFetchFailure:
    """G2: when `_fetch_site_pages` itself raises (not classified as a per-site
    Graph 4xx), Phase 5 yields a single EntityFailure keyed on the site URL
    and the generator returns cleanly."""

    def test_runtime_error_in_fetch_yields_entity_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connector = _setup_connector(monkeypatch)
        connector.include_site_pages = True

        def fake_fetch(
            self: SharepointConnector,  # noqa: ARG001
            site_descriptor: SiteDescriptor,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
        ) -> list[dict[str, Any]]:
            raise RuntimeError("pages endpoint blew up")

        monkeypatch.setattr(SharepointConnector, "_fetch_site_pages", fake_fetch)

        checkpoint = _build_phase5_checkpoint()
        gen = connector._load_from_checkpoint(
            _EPOCH_START, _END_TS, checkpoint, include_permissions=False
        )
        yielded, _final_cp = _consume_generator(gen)

        assert _docs_from(yielded) == []
        failures = _failures_from(yielded)
        assert len(failures) == 1
        assert failures[0].failed_entity is not None
        assert failures[0].failed_entity.entity_id == SITE_URL
        assert "pages endpoint blew up" in failures[0].failure_message


class TestSitePagesPerPageFailure:
    """G3: when one page fails to convert, the others still come through and
    the broken page is reported as a per-page ConnectorFailure."""

    def test_one_bad_page_yields_document_failure_and_others_succeed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connector = _setup_connector(monkeypatch)
        connector.include_site_pages = True

        good_page_1 = {
            "id": "good-1",
            "webUrl": f"{SITE_URL}/SitePages/Good1.aspx",
            "title": "Good 1",
        }
        bad_page = {
            "id": "bad-1",
            "webUrl": f"{SITE_URL}/SitePages/Bad.aspx",
            "title": "Bad",
        }
        good_page_2 = {
            "id": "good-2",
            "webUrl": f"{SITE_URL}/SitePages/Good2.aspx",
            "title": "Good 2",
        }

        def fake_fetch(
            self: SharepointConnector,  # noqa: ARG001
            site_descriptor: SiteDescriptor,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
        ) -> list[dict[str, Any]]:
            return [good_page_1, bad_page, good_page_2]

        monkeypatch.setattr(SharepointConnector, "_fetch_site_pages", fake_fetch)

        def fake_convert(
            page: dict[str, Any],
            drive_name: str | None,  # noqa: ARG001
            client_ctx: Any,  # noqa: ARG001
            graph_client: Any,  # noqa: ARG001
            include_permissions: bool = False,  # noqa: ARG001
            parent_hierarchy_raw_node_id: str | None = None,  # noqa: ARG001
            treat_sharing_link_as_public: bool = False,  # noqa: ARG001
        ) -> Document:
            if page["id"] == "bad-1":
                raise ValueError("malformed canvasLayout")
            return Document(
                id=page["id"],
                source=DocumentSource.SHAREPOINT,
                semantic_identifier=page["title"],
                metadata={},
                sections=[TextSection(link=page["webUrl"], text="content")],
            )

        _mock_convert_sitepage(monkeypatch, fake_convert)

        checkpoint = _build_phase5_checkpoint()
        gen = connector._load_from_checkpoint(
            _EPOCH_START, _END_TS, checkpoint, include_permissions=False
        )
        yielded, _final_cp = _consume_generator(gen)

        docs = _docs_from(yielded)
        failures = _failures_from(yielded)

        assert [d.id for d in docs] == ["good-1", "good-2"]
        assert len(failures) == 1
        failed_doc = failures[0].failed_document
        assert failed_doc is not None
        assert isinstance(failed_doc, DocumentFailure)
        assert failed_doc.document_id == "bad-1"
        assert failed_doc.document_link == bad_page["webUrl"]
        assert "malformed canvasLayout" in failures[0].failure_message

    def test_bad_page_without_id_yields_entity_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A page that fails to convert AND has no id falls back to an
        EntityFailure (we don't have anything to attach a DocumentFailure to)."""
        connector = _setup_connector(monkeypatch)
        connector.include_site_pages = True

        idless_page = {"webUrl": f"{SITE_URL}/SitePages/Orphan.aspx"}

        def fake_fetch(
            self: SharepointConnector,  # noqa: ARG001
            site_descriptor: SiteDescriptor,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
        ) -> list[dict[str, Any]]:
            return [idless_page]

        monkeypatch.setattr(SharepointConnector, "_fetch_site_pages", fake_fetch)

        def fake_convert(
            page: dict[str, Any],  # noqa: ARG001
            drive_name: str | None,  # noqa: ARG001
            client_ctx: Any,  # noqa: ARG001
            graph_client: Any,  # noqa: ARG001
            include_permissions: bool = False,  # noqa: ARG001
            parent_hierarchy_raw_node_id: str | None = None,  # noqa: ARG001
            treat_sharing_link_as_public: bool = False,  # noqa: ARG001
        ) -> Document:
            raise KeyError("id")

        _mock_convert_sitepage(monkeypatch, fake_convert)

        checkpoint = _build_phase5_checkpoint()
        gen = connector._load_from_checkpoint(
            _EPOCH_START, _END_TS, checkpoint, include_permissions=False
        )
        yielded, _final_cp = _consume_generator(gen)

        assert _docs_from(yielded) == []
        failures = _failures_from(yielded)
        assert len(failures) == 1
        assert failures[0].failed_entity is not None
        assert (
            failures[0].failed_entity.entity_id
            == f"{SITE_URL}|site_page|{idless_page['webUrl']}"
        )

    def test_all_pages_fail_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even when every page fails, the generator completes — one
        ConnectorFailure per page, no crash."""
        connector = _setup_connector(monkeypatch)
        connector.include_site_pages = True

        pages = [
            {"id": "p1", "webUrl": f"{SITE_URL}/SitePages/A.aspx"},
            {"id": "p2", "webUrl": f"{SITE_URL}/SitePages/B.aspx"},
        ]

        def fake_fetch(
            self: SharepointConnector,  # noqa: ARG001
            site_descriptor: SiteDescriptor,  # noqa: ARG001
            start: datetime | None = None,  # noqa: ARG001
            end: datetime | None = None,  # noqa: ARG001
        ) -> list[dict[str, Any]]:
            return pages

        monkeypatch.setattr(SharepointConnector, "_fetch_site_pages", fake_fetch)

        def fake_convert(*_args: Any, **_kwargs: Any) -> Document:
            raise RuntimeError("conversion always fails")

        _mock_convert_sitepage(monkeypatch, fake_convert)

        checkpoint = _build_phase5_checkpoint()
        gen = connector._load_from_checkpoint(
            _EPOCH_START, _END_TS, checkpoint, include_permissions=False
        )
        yielded, _final_cp = _consume_generator(gen)

        assert _docs_from(yielded) == []
        failures = _failures_from(yielded)
        assert len(failures) == 2
        assert {
            f.failed_document.document_id for f in failures if f.failed_document
        } == {
            "p1",
            "p2",
        }
