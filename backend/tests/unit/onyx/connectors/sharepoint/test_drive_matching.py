from __future__ import annotations

from collections import deque
from collections.abc import Generator, Sequence
from datetime import datetime
from typing import Any

import pytest

from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient
from onyx.connectors.models import Document, DocumentSource, TextSection
from onyx.connectors.sharepoint import connector as sp_connector
from onyx.connectors.sharepoint.connector import (
    SHARED_DOCUMENTS_MAP,
    SharepointConnector,
    SharepointConnectorCheckpoint,
    SiteDescriptor,
)


class _FakeQuery:
    def __init__(self, payload: Sequence[Any]) -> None:
        self._payload = payload

    def execute_query(self) -> Sequence[Any]:
        return self._payload


class _FakeDrive:
    def __init__(self, name: str, drive_type: str | None = None) -> None:
        self.name = name
        self.drive_type = drive_type
        self.id = f"fake-drive-id-{name}"
        self.web_url = f"https://example.sharepoint.com/sites/sample/{name}"


class _FakeDrivesCollection:
    def __init__(self, drives: Sequence[_FakeDrive]) -> None:
        self._drives = drives

    def get(self) -> _FakeQuery:
        return _FakeQuery(list(self._drives))


class _FakeSite:
    def __init__(self, drives: Sequence[_FakeDrive]) -> None:
        self.drives = _FakeDrivesCollection(drives)


class _FakeSites:
    def __init__(self, drives: Sequence[_FakeDrive]) -> None:
        self._drives = drives

    def get_by_url(self, _url: str) -> _FakeSite:
        return _FakeSite(self._drives)


class _FakeGraphClient:
    def __init__(self, drives: Sequence[_FakeDrive]) -> None:
        self.sites = _FakeSites(drives)


_SAMPLE_ITEM = DriveItemData(
    id="item-1",
    name="sample.pdf",
    web_url="https://example.sharepoint.com/sites/sample/sample.pdf",
    parent_reference_path=None,
    drive_id="fake-drive-id",
)


def _build_connector(drives: Sequence[_FakeDrive]) -> SharepointConnector:
    connector = SharepointConnector()
    connector._graph_client = _FakeGraphClient(drives)  # ty: ignore[invalid-assignment]
    return connector


def _fake_iter_drive_items_paged(
    client: GraphApiClient,  # noqa: ARG001
    drive_id: str,  # noqa: ARG001
    folder_path: str | None = None,  # noqa: ARG001
    start: datetime | None = None,  # noqa: ARG001
    end: datetime | None = None,  # noqa: ARG001
    page_size: int = 200,  # noqa: ARG001
) -> Generator[DriveItemData, None, None]:
    yield _SAMPLE_ITEM


def _fake_iter_drive_items_delta(
    client: GraphApiClient,  # noqa: ARG001
    drive_id: str,  # noqa: ARG001
    start: datetime | None = None,  # noqa: ARG001
    end: datetime | None = None,  # noqa: ARG001
    page_size: int = 200,  # noqa: ARG001
) -> Generator[DriveItemData, None, None]:
    yield _SAMPLE_ITEM


@pytest.mark.parametrize(
    ("requested_drive_name", "graph_drive_name"),
    [
        ("Shared Documents", "Documents"),
        ("Freigegebene Dokumente", "Dokumente"),
        ("Documentos compartidos", "Documentos"),
    ],
)
def test_fetch_driveitems_matches_international_drive_names(
    requested_drive_name: str,
    graph_drive_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _build_connector([_FakeDrive(graph_drive_name)])
    site_descriptor = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name=requested_drive_name,
        folder_path=None,
    )

    monkeypatch.setattr(
        sp_connector,
        "iter_drive_items_delta",
        _fake_iter_drive_items_delta,
    )

    results = list(connector._fetch_driveitems(site_descriptor=site_descriptor))

    assert len(results) == 1
    drive_item, returned_drive_name, drive_web_url = results[0]
    assert drive_item.id == _SAMPLE_ITEM.id
    assert returned_drive_name == requested_drive_name
    assert drive_web_url is not None


@pytest.mark.parametrize(
    ("requested_drive_name", "graph_drive_name"),
    [
        ("Shared Documents", "Documents"),
        ("Freigegebene Dokumente", "Dokumente"),
        ("Documentos compartidos", "Documentos"),
    ],
)
def test_get_drive_items_for_drive_id_matches_map(
    requested_drive_name: str,
    graph_drive_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _build_connector([_FakeDrive(graph_drive_name)])
    site_descriptor = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name=requested_drive_name,
        folder_path=None,
    )

    monkeypatch.setattr(
        sp_connector,
        "iter_drive_items_delta",
        _fake_iter_drive_items_delta,
    )

    items_iter = connector._get_drive_items_for_drive_id(
        site_descriptor=site_descriptor,
        drive_id="fake-drive-id",
    )

    results = list(items_iter)
    assert len(results) == 1
    assert results[0].id == _SAMPLE_ITEM.id


def test_load_from_checkpoint_maps_drive_name(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = SharepointConnector()
    connector._graph_client = object()  # ty: ignore[invalid-assignment]
    connector.include_site_pages = False

    captured_drive_names: list[str] = []
    sample_item = DriveItemData(
        id="doc-1",
        name="sample.pdf",
        web_url="https://example.sharepoint.com/sites/sample/sample.pdf",
        parent_reference_path=None,
        drive_id="fake-drive-id",
    )

    def fake_resolve_drive(
        self: SharepointConnector,  # noqa: ARG001
        site_descriptor: SiteDescriptor,  # noqa: ARG001
        drive_name: str,
    ) -> tuple[str, str | None]:
        assert drive_name == "Documents"
        return (
            "fake-drive-id",
            "https://example.sharepoint.com/sites/sample/Documents",
        )

    def fake_fetch_one_delta_page(
        client: Any,  # noqa: ARG001
        page_url: str,  # noqa: ARG001
        drive_id: str,  # noqa: ARG001
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> tuple[list[DriveItemData], str | None]:
        return [sample_item], None

    def fake_convert(
        driveitem: DriveItemData,  # noqa: ARG001
        drive_name: str,
        ctx: Any,  # noqa: ARG001
        graph_client: Any,  # noqa: ARG001
        graph_api_base: str,  # noqa: ARG001
        include_permissions: bool,  # noqa: ARG001
        parent_hierarchy_raw_node_id: str | None = None,  # noqa: ARG001
        access_token: str | None = None,  # noqa: ARG001
        treat_sharing_link_as_public: bool = False,  # noqa: ARG001
        raw_file_callback: Any = None,  # noqa: ARG001
        permission_cache: Any = None,  # noqa: ARG001
    ) -> Document:
        captured_drive_names.append(drive_name)
        return Document(
            id="doc-1",
            source=DocumentSource.SHAREPOINT,
            semantic_identifier="sample.pdf",
            metadata={},
            sections=[TextSection(link="https://example.com", text="content")],
        )

    def fake_get_access_token(self: SharepointConnector) -> str:  # noqa: ARG001
        return "fake-access-token"

    monkeypatch.setattr(
        SharepointConnector,
        "_resolve_drive",
        fake_resolve_drive,
    )
    monkeypatch.setattr(
        sp_connector,
        "fetch_one_delta_page",
        fake_fetch_one_delta_page,
    )
    monkeypatch.setattr(
        "onyx.connectors.sharepoint.connector._convert_driveitem_to_document_with_permissions",
        fake_convert,
    )
    monkeypatch.setattr(
        SharepointConnector,
        "_get_graph_access_token",
        fake_get_access_token,
    )

    checkpoint = SharepointConnectorCheckpoint(has_more=True)
    checkpoint.cached_site_descriptors = deque()
    checkpoint.current_site_descriptor = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name=SHARED_DOCUMENTS_MAP["Documents"],
        folder_path=None,
    )
    checkpoint.cached_drive_names = deque(["Documents"])
    checkpoint.current_drive_name = None
    checkpoint.process_site_pages = False

    generator = connector._load_from_checkpoint(
        start=0,
        end=0,
        checkpoint=checkpoint,
        include_permissions=False,
    )

    all_yielded: list[Any] = []
    try:
        while True:
            all_yielded.append(next(generator))
    except StopIteration:
        pass

    from onyx.connectors.models import HierarchyNode

    documents = [item for item in all_yielded if not isinstance(item, HierarchyNode)]
    hierarchy_nodes = [item for item in all_yielded if isinstance(item, HierarchyNode)]

    assert len(documents) == 1
    assert captured_drive_names == [SHARED_DOCUMENTS_MAP["Documents"]]
    assert len(hierarchy_nodes) >= 1


_PERSONAL_SITE_URL = "https://example-my.sharepoint.com/personal/user_example_com"


def _resolve_personal(drives: list[_FakeDrive]) -> tuple[str, str | None] | None:
    connector = _build_connector(drives)
    site_descriptor = SiteDescriptor(
        url=_PERSONAL_SITE_URL,
        drive_name="Documents",
        folder_path=None,
    )
    return connector._resolve_drive(site_descriptor, "Documents")


def test_resolve_drive_personal_picks_by_drive_type_not_position() -> None:
    """The user's OneDrive must be selected by driveType regardless of order."""
    extra_library = _FakeDrive("Extra Library", drive_type="documentLibrary")
    onedrive = _FakeDrive("OneDrive", drive_type="business")

    # OneDrive is second in the (unordered) response; positional selection would
    # have picked the wrong library.
    result = _resolve_personal([extra_library, onedrive])

    assert result is not None
    drive_id, _ = result
    assert drive_id == onedrive.id


def test_resolve_drive_personal_falls_back_to_name_when_type_missing() -> None:
    extra_library = _FakeDrive("Extra Library", drive_type="documentLibrary")
    onedrive = _FakeDrive("OneDrive", drive_type=None)

    result = _resolve_personal([extra_library, onedrive])

    assert result is not None
    drive_id, _ = result
    assert drive_id == onedrive.id


def test_resolve_drive_personal_prefers_type_over_name_collision() -> None:
    """A uniquely-typed primary drive wins even if another library reuses a name."""
    # Localized primary drive name so resolution must rely on driveType.
    primary = _FakeDrive("Mon lecteur OneDrive", drive_type="business")
    # An extra library that happens to carry a fallback OneDrive name but is not
    # the user's primary drive.
    extra_library = _FakeDrive("OneDrive", drive_type="documentLibrary")

    result = _resolve_personal([extra_library, primary])

    assert result is not None
    drive_id, _ = result
    assert drive_id == primary.id


def test_resolve_drive_personal_ambiguous_returns_none() -> None:
    """Refuse to guess when multiple primary-OneDrive candidates exist."""
    first = _FakeDrive("OneDrive", drive_type="business")
    second = _FakeDrive("Second OneDrive", drive_type="personal")

    assert _resolve_personal([first, second]) is None


def test_get_drive_items_uses_delta_when_no_folder_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When folder_path is None, _get_drive_items_for_drive_id should use delta."""
    connector = _build_connector([_FakeDrive("Documents")])
    site = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name="Documents",
        folder_path=None,
    )

    called_method: list[str] = []

    def fake_delta(
        client: GraphApiClient,  # noqa: ARG001
        drive_id: str,  # noqa: ARG001
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        called_method.append("delta")
        yield _SAMPLE_ITEM

    def fake_paged(
        client: GraphApiClient,  # noqa: ARG001
        drive_id: str,  # noqa: ARG001
        folder_path: str | None = None,  # noqa: ARG001
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        called_method.append("paged")
        yield _SAMPLE_ITEM

    monkeypatch.setattr(sp_connector, "iter_drive_items_delta", fake_delta)
    monkeypatch.setattr(sp_connector, "iter_drive_items_paged", fake_paged)

    items = connector._get_drive_items_for_drive_id(site, "fake-drive-id")
    list(items)

    assert called_method == ["delta"]


def test_get_drive_items_uses_paged_when_folder_path_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When folder_path is set, _get_drive_items_for_drive_id should use BFS."""
    connector = _build_connector([_FakeDrive("Documents")])
    site = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name="Documents",
        folder_path="Engineering/Docs",
    )

    called_method: list[str] = []

    def fake_delta(
        client: GraphApiClient,  # noqa: ARG001
        drive_id: str,  # noqa: ARG001
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        called_method.append("delta")
        yield _SAMPLE_ITEM

    def fake_paged(
        client: GraphApiClient,  # noqa: ARG001
        drive_id: str,  # noqa: ARG001
        folder_path: str | None = None,  # noqa: ARG001
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        called_method.append("paged")
        yield _SAMPLE_ITEM

    monkeypatch.setattr(sp_connector, "iter_drive_items_delta", fake_delta)
    monkeypatch.setattr(sp_connector, "iter_drive_items_paged", fake_paged)

    items = connector._get_drive_items_for_drive_id(site, "fake-drive-id")
    list(items)

    assert called_method == ["paged"]
