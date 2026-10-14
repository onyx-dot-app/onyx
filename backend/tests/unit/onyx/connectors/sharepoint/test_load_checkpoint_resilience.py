"""SharePoint checkpoint resilience tests."""

from collections import deque
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import pytest

from onyx.connectors.microsoft_utils.drive_delta import (
    DriveDeltaFetchResult,
    DriveDeltaPage,
)
from onyx.connectors.microsoft_utils.drive_items import DriveFolderReference
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    DocumentSource,
    EntityFailure,
    HierarchyNode,
    TextSection,
)
from onyx.connectors.sharepoint.connector import (
    DriveItemData,
    SharepointConnector,
    SharepointConnectorCheckpoint,
    SiteDescriptor,
    SiteDrive,
)
from onyx.connectors.sharepoint.source_operations import SharepointSourceOperations
from tests.unit.onyx.connectors.sharepoint.sharepoint_gateway_fakes import (
    connector_with_gateway,
    stub_operation,
)

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


def _delta_result(item: DriveItemData) -> DriveDeltaFetchResult:
    return DriveDeltaFetchResult(
        page=DriveDeltaPage.model_validate(
            {
                "value": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "webUrl": item.web_url,
                        "parentReference": {"driveId": item.drive_id},
                    }
                ]
            }
        )
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


def _setup_connector() -> SharepointConnector:
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


def _build_phase3_checkpoint(
    folder_path: str | None = None,
) -> SharepointConnectorCheckpoint:
    """Checkpoint ready to enter Phase 3 (site initialised, one drive queued)."""
    cp = SharepointConnectorCheckpoint(has_more=True)
    cp.cached_site_descriptors = deque()
    cp.current_site_descriptor = SiteDescriptor(
        url=SITE_URL, drive_name=None, folder_path=folder_path
    )
    cp.cached_drives = deque(
        [
            SiteDrive(
                drive_id=DRIVE_ID,
                list_id="fake-list-id",
                display_name=DRIVE_NAME,
                web_url=DRIVE_WEB_URL,
            )
        ]
    )
    cp.process_site_pages = False
    return cp


def _build_phase5_checkpoint() -> SharepointConnectorCheckpoint:
    """Checkpoint ready to enter Phase 5 directly (drives done, site pages flagged)."""
    cp = SharepointConnectorCheckpoint(has_more=True)
    cp.cached_site_descriptors = deque()
    cp.current_site_descriptor = SiteDescriptor(
        url=SITE_URL, drive_name=None, folder_path=None
    )
    cp.cached_drives = deque()
    cp.process_site_pages = True
    return cp


def test_docs_only_indexing_accepts_drive_without_list_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _setup_connector()
    _mock_convert(monkeypatch)
    checkpoint = _build_phase3_checkpoint()
    assert checkpoint.cached_drives is not None
    checkpoint.cached_drives[0].list_id = None
    stub_operation(
        connector.ops,
        "get_delta_page",
        lambda **_kwargs: _delta_result(_make_item("doc")),
    )

    yielded, _ = _consume_generator(
        connector._load_from_checkpoint(
            _EPOCH_START, _END_TS, checkpoint, include_permissions=False
        )
    )

    assert [document.id for document in _docs_from(yielded)] == ["doc"]
    assert not _failures_from(yielded)


def test_checkpoint_accepts_drive_without_list_id() -> None:
    checkpoint = SharepointConnectorCheckpoint.model_validate(
        {
            "has_more": True,
            "cached_drives": [
                {
                    "drive_id": DRIVE_ID,
                    "display_name": DRIVE_NAME,
                    "web_url": DRIVE_WEB_URL,
                }
            ],
        }
    )

    assert checkpoint.cached_drives is not None
    assert checkpoint.cached_drives[0].list_id is None


def test_permission_indexing_skips_drive_without_list_id() -> None:
    connector = _setup_connector()
    checkpoint = _build_phase3_checkpoint()
    assert checkpoint.cached_drives is not None
    checkpoint.cached_drives[0].list_id = None

    yielded, final_checkpoint = _consume_generator(
        connector._load_from_checkpoint(
            _EPOCH_START, _END_TS, checkpoint, include_permissions=True
        )
    )

    failures = _failures_from(yielded)
    assert len(failures) == 1
    assert "requires a list ID" in failures[0].failure_message
    assert final_checkpoint.current_drive is None


def test_drive_init_failure_yields_the_next_site_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A site whose drives fail to load (e.g. throttled) moves on to the next
    site, which must still get its hierarchy node: its drives use it as
    their parent."""
    connector = _setup_connector()
    next_site_url = "https://example.sharepoint.com/sites/next"

    def failing_get_drives(_site_url: str) -> list[SiteDrive]:
        raise RuntimeError("The request has been throttled")

    monkeypatch.setattr(connector, "_get_drives_for_site", failing_get_drives)
    checkpoint = SharepointConnectorCheckpoint(has_more=True)
    checkpoint.cached_site_descriptors = deque(
        [SiteDescriptor(url=next_site_url, drive_name=None, folder_path=None)]
    )
    checkpoint.current_site_descriptor = SiteDescriptor(
        url=SITE_URL, drive_name=None, folder_path=None
    )

    yielded, final_checkpoint = _consume_generator(
        connector._load_from_checkpoint(
            _EPOCH_START, _END_TS, checkpoint, include_permissions=False
        )
    )

    assert len(_failures_from(yielded)) == 1
    site_nodes = [y for y in yielded if isinstance(y, HierarchyNode)]
    assert [node.raw_node_id for node in site_nodes] == [next_site_url]
    assert final_checkpoint.current_site_descriptor is not None
    assert final_checkpoint.current_site_descriptor.url == next_site_url


# ---------------------------------------------------------------------------
# G1 — BFS-mode generator failures mid-iteration
# ---------------------------------------------------------------------------


class TestBfsIterationFailure:
    """When `iter_drive_items_paged` (BFS path) raises after yielding some
    items, items emitted before the raise are kept, an EntityFailure is
    yielded for the drive, the drive checkpoint state is cleared, and the
    generator returns cleanly instead of aborting the attempt."""

    def test_bfs_generator_failure_yields_entity_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        good_items = [_make_item("a"), _make_item("b")]

        def fake_iter_paged(
            *,
            drive_id: str,  # noqa: ARG001
            folder_id: str | None,  # noqa: ARG001
            start: datetime | None,  # noqa: ARG001
            end: datetime | None,  # noqa: ARG001
        ) -> Generator[DriveItemData, None, None]:
            yield from good_items
            raise RuntimeError("graph 500 mid-page")

        stub_operation(connector.ops, "iter_folder_items", fake_iter_paged)

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
        assert failed_entity.entity_id == f"{DRIVE_ID}|bfs_iter"
        assert "graph 500 mid-page" in failures[0].failure_message

        # Drive state cleared so resume doesn't loop on the broken drive.
        assert final_cp.current_drive is None
        assert final_cp.current_drive_delta_next_link is None

    def test_bfs_generator_failure_at_start_still_yields_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A raise before any item is yielded still produces an EntityFailure
        rather than crashing the attempt."""
        connector = _setup_connector()
        _mock_convert(monkeypatch)

        def fake_iter_paged(
            *,
            drive_id: str,  # noqa: ARG001
            folder_id: str | None,  # noqa: ARG001
            start: datetime | None,  # noqa: ARG001
            end: datetime | None,  # noqa: ARG001
        ) -> Generator[DriveItemData, None, None]:
            raise RuntimeError("connection reset")
            yield  # pragma: no cover  # make this a generator

        stub_operation(connector.ops, "iter_folder_items", fake_iter_paged)

        checkpoint = _build_phase3_checkpoint(folder_path="Engineering/Docs")
        gen = connector._load_from_checkpoint(
            _EPOCH_START, _END_TS, checkpoint, include_permissions=False
        )
        yielded, final_cp = _consume_generator(gen)

        assert _docs_from(yielded) == []
        failures = _failures_from(yielded)
        assert len(failures) == 1
        assert failures[0].failed_entity is not None
        assert failures[0].failed_entity.entity_id == f"{DRIVE_ID}|bfs_iter"
        assert final_cp.current_drive is None


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
        connector = _setup_connector()
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
        connector = _setup_connector()
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
            site_name: str | None,  # noqa: ARG001
            ops: SharepointSourceOperations,  # noqa: ARG001
            site_url: str,  # noqa: ARG001
            permission_cache: Any,  # noqa: ARG001
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
        connector = _setup_connector()
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
            site_name: str | None,  # noqa: ARG001
            ops: SharepointSourceOperations,  # noqa: ARG001
            site_url: str,  # noqa: ARG001
            permission_cache: Any,  # noqa: ARG001
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
        connector = _setup_connector()
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
