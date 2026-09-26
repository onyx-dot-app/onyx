from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Generator, Sequence
from datetime import datetime
from typing import Any, NoReturn
from urllib.parse import quote

import pytest
import requests
from office365.graph_client import GraphClient
from office365.onedrive.drives.drive import Drive
from office365.runtime.client_request_exception import ClientRequestException
from requests import Response
from requests.exceptions import HTTPError

from onyx.connectors.microsoft_utils.drive_delta import SHAREPOINT_IDS_PROPERTY
from onyx.connectors.microsoft_utils.drive_items import (
    DriveFolderReference,
    DriveItemData,
)
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient
from onyx.connectors.models import (
    Document,
    DocumentSource,
    HierarchyNode,
    TextSection,
)
from onyx.connectors.sharepoint import connector as sp_connector
from onyx.connectors.sharepoint.connector import (
    DRIVE_SELECT_FIELDS,
    SHARED_DOCUMENTS_MAP,
    SharepointConnector,
    SharepointConnectorCheckpoint,
    SiteDescriptor,
    SiteDrive,
)
from onyx.db.enums import HierarchyNodeType


class _FakeQuery:
    def __init__(self, payload: Sequence[Any]) -> None:
        self._payload = payload

    def execute_query(self) -> Sequence[Any]:
        return self._payload


class _FakeDrive:
    def __init__(
        self,
        name: str,
        drive_type: str | None = None,
        url_name: str | None = None,
        list_id: str | None = None,
    ) -> None:
        self.name = name
        self.drive_type = drive_type
        self.id = f"fake-drive-id-{name}"
        self.properties = {
            SHAREPOINT_IDS_PROPERTY: {"listId": list_id or f"list-id-{name}"}
        }
        self.web_url = (
            f"https://example.sharepoint.com/sites/sample/{quote(url_name or name)}"
        )


class _FakeDrivesCollection:
    def __init__(
        self,
        drives: Sequence[_FakeDrive],
        first_page_size: int | None = None,
    ) -> None:
        self._drives = drives
        self._first_page_size = first_page_size
        self.selected_fields: list[str] | None = None

    def select(self, fields: list[str]) -> "_FakeDrivesCollection":
        self.selected_fields = fields
        return self

    def get(self) -> _FakeQuery:
        return _FakeQuery(list(self._drives[: self._first_page_size]))

    def get_all(self, page_loaded: Callable[[Any], None]) -> _FakeQuery:
        page_loaded(self)
        return _FakeQuery(list(self._drives))


class _FakeSite:
    def __init__(self, drives: _FakeDrivesCollection) -> None:
        self.drives = drives


class _FakeSites:
    def __init__(
        self,
        drives: Sequence[_FakeDrive],
        first_page_size: int | None = None,
    ) -> None:
        self.drives = _FakeDrivesCollection(drives, first_page_size)

    def get_by_url(self, _url: str) -> _FakeSite:
        return _FakeSite(self.drives)


class _FakeGraphClient:
    def __init__(
        self,
        drives: Sequence[_FakeDrive],
        first_page_size: int | None = None,
    ) -> None:
        self.sites = _FakeSites(drives, first_page_size)


_SAMPLE_ITEM = DriveItemData(
    id="item-1",
    name="sample.pdf",
    web_url="https://example.sharepoint.com/sites/sample/sample.pdf",
    parent_reference_path=None,
    drive_id="fake-drive-id",
)


def _build_connector(
    drives: Sequence[_FakeDrive],
    first_page_size: int | None = None,
) -> SharepointConnector:
    connector = SharepointConnector()
    connector._graph_client = _FakeGraphClient(  # ty: ignore[invalid-assignment]
        drives, first_page_size
    )
    return connector


def _fake_iter_drive_items_paged(
    client: GraphApiClient,  # noqa: ARG001
    drive_id: str,  # noqa: ARG001
    folder_path: str | None = None,  # noqa: ARG001
    folder_id: str | None = None,  # noqa: ARG001
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
    connector = _build_connector(
        [_FakeDrive(graph_drive_name, url_name=requested_drive_name)]
    )
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
    assert results[0].driveitem.id == _SAMPLE_ITEM.id
    assert results[0].drive.display_name == graph_drive_name
    assert results[0].drive.web_url is not None


def test_fetch_driveitems_uses_drive_id_without_list_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drive = _FakeDrive("System")
    drive.properties = {}
    connector = _build_connector([drive])
    traversed_drive_ids: list[str] = []

    def fake_delta(
        client: GraphApiClient,  # noqa: ARG001
        drive_id: str,
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        traversed_drive_ids.append(drive_id)
        yield _SAMPLE_ITEM

    monkeypatch.setattr(sp_connector, "iter_drive_items_delta", fake_delta)

    results = list(connector._fetch_driveitems(site_descriptor=_site()))

    assert traversed_drive_ids == [drive.id]
    assert results[0].drive.list_id is None


def test_load_from_checkpoint_maps_drive_name(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _build_connector([_FakeDrive("Documents")])
    connector.include_site_pages = False

    captured_drive_names: list[str] = []
    sample_item = DriveItemData(
        id="doc-1",
        name="sample.pdf",
        web_url="https://example.sharepoint.com/sites/sample/sample.pdf",
        parent_reference_path=None,
        drive_id="fake-drive-id",
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
        drive: SiteDrive,
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
        captured_drive_names.append(drive.display_name)
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
    checkpoint.legacy_cached_drive_names = deque(["Documents"])
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
    assert captured_drive_names == ["Documents"]
    assert len(hierarchy_nodes) >= 1


def test_deleted_legacy_current_drive_preserves_queue_after_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remaining = _FakeDrive("Remaining")
    connector = _build_connector([remaining])
    connector.include_site_pages = False
    monkeypatch.setattr(
        sp_connector, "fetch_one_delta_page", lambda *_, **__: ([_SAMPLE_ITEM], None)
    )
    monkeypatch.setattr(
        sp_connector,
        "_convert_driveitem_to_document_with_permissions",
        lambda item, *_args, **_kwargs: Document(
            id=item.id,
            source=DocumentSource.SHAREPOINT,
            semantic_identifier=item.name,
            metadata={},
            sections=[TextSection(link=item.web_url, text="content")],
        ),
    )
    monkeypatch.setattr(
        SharepointConnector, "_get_graph_access_token", lambda _self: "token"
    )
    checkpoint = SharepointConnectorCheckpoint.model_validate(
        {
            "has_more": True,
            "cached_site_descriptors": [],
            "current_site_descriptor": {
                "url": _STRIPPED_URL_SITE.url,
                "drive_name": None,
                "folder_path": None,
            },
            "cached_drive_names": ["Remaining"],
            "current_drive_id": "deleted-drive-id",
            "current_drive_name": "Deleted",
        }
    )

    connector._migrate_legacy_drive_checkpoint(checkpoint)
    restored = SharepointConnectorCheckpoint.model_validate_json(
        checkpoint.model_dump_json()
    )

    assert restored.current_drive is None
    assert [drive.drive_id for drive in restored.cached_drives or []] == [remaining.id]
    yielded = list(
        connector._load_from_checkpoint(0, 0, restored, include_permissions=False)
    )
    assert any(isinstance(item, Document) for item in yielded)


_PERSONAL_SITE_URL = "https://example-my.sharepoint.com/personal/user_example_com"


def _resolve_personal(drives: list[_FakeDrive]) -> SiteDrive | None:
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
    assert result.drive_id == onedrive.id


def test_resolve_drive_personal_selects_url_segment_between_business_drives() -> None:
    onedrive = _FakeDrive("OneDrive", drive_type="business", url_name="Documents")
    cache = _FakeDrive(
        "PersonalCacheLibrary",
        drive_type="business",
        url_name="PersonalCacheLibrary",
    )

    result = _resolve_personal([cache, onedrive])

    assert result is not None
    assert result.drive_id == onedrive.id
    assert result.list_id == "list-id-OneDrive"
    assert result.display_name == "OneDrive"


def test_resolve_drive_personal_does_not_fall_back_to_name() -> None:
    extra_library = _FakeDrive("Extra Library", drive_type="documentLibrary")
    onedrive = _FakeDrive("OneDrive", drive_type=None)

    result = _resolve_personal([extra_library, onedrive])

    assert result is None


def test_resolve_drive_personal_prefers_type_over_name_collision() -> None:
    """A uniquely-typed primary drive wins even if another library reuses a name."""
    # Localized primary drive name so resolution must rely on driveType.
    primary = _FakeDrive("Mon lecteur OneDrive", drive_type="business")
    # An extra library that happens to carry a fallback OneDrive name but is not
    # the user's primary drive.
    extra_library = _FakeDrive("OneDrive", drive_type="documentLibrary")

    result = _resolve_personal([extra_library, primary])

    assert result is not None
    assert result.drive_id == primary.id


def test_resolve_drive_personal_ambiguous_raises() -> None:
    """Refuse to guess when multiple primary-OneDrive candidates exist."""
    first = _FakeDrive("OneDrive", drive_type="business")
    second = _FakeDrive("Second OneDrive", drive_type="personal")

    with pytest.raises(ValueError, match="unambiguously"):
        _resolve_personal([first, second])


# SharePoint strips "&" from the library URL, so "R&D Library" lives at "RD Library".
_STRIPPED_URL_DRIVE = _FakeDrive("R&D Library", url_name="RD Library")
_STRIPPED_URL_SITE = SiteDescriptor(
    url="https://example.sharepoint.com/sites/sample",
    drive_name="RD Library",
    folder_path=None,
)


def test_resolve_drive_matches_library_url_and_returns_display_name() -> None:
    connector = _build_connector([_FakeDrive("Documents"), _STRIPPED_URL_DRIVE])

    result = connector._resolve_drive(_STRIPPED_URL_SITE, "RD Library")

    assert result is not None
    assert result.drive_id == _STRIPPED_URL_DRIVE.id
    assert result.display_name == "R&D Library"


def _odata_mapped_drive(include_sharepoint_ids: bool) -> Drive:
    graph_client = GraphClient(lambda: {"access_token": "unused"})
    drives = graph_client.sites["site-id"].drives.select(DRIVE_SELECT_FIELDS).get()
    properties: dict[str, Any] = {
        "id": "drive-id",
        "name": "Documents",
        "webUrl": "https://example.sharepoint.com/sites/sample/Documents",
        "driveType": "documentLibrary",
    }
    if include_sharepoint_ids:
        properties[SHAREPOINT_IDS_PROPERTY] = {"listId": "list-id"}

    response = Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps({"value": [properties]}).encode()
    graph_client.pending_request().process_response(response, graph_client._queries[0])
    return drives[0]


def test_site_drive_reads_sharepoint_ids_from_odata_mapped_properties() -> None:
    drive = _odata_mapped_drive(include_sharepoint_ids=True)

    result = SharepointConnector._site_drive_from_graph(drive)

    assert drive.properties[SHAREPOINT_IDS_PROPERTY] == {"listId": "list-id"}
    assert result.list_id == "list-id"


def test_site_drive_without_sharepoint_ids_has_no_list_id() -> None:
    drive = _odata_mapped_drive(include_sharepoint_ids=False)

    result = SharepointConnector._site_drive_from_graph(drive)

    assert result.list_id is None


def test_configured_drive_selection_reads_later_page() -> None:
    target = _FakeDrive("Target")
    connector = _build_connector(
        [_FakeDrive("First Page"), target],
        first_page_size=1,
    )
    site = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name="Target",
        folder_path=None,
    )

    result = connector._resolve_drive(site, "Target")

    assert result is not None
    assert result.drive_id == target.id


def test_slim_all_drive_traversal_reads_later_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drives = [_FakeDrive("First Page"), _FakeDrive("Second Page")]
    connector = _build_connector(drives, first_page_size=1)
    monkeypatch.setattr(
        sp_connector, "iter_drive_items_delta", _fake_iter_drive_items_delta
    )

    results = list(connector._fetch_driveitems(_site()))

    assert [result.drive.drive_id for result in results] == [
        drive.id for drive in drives
    ]


def test_resolve_drive_prefers_library_url_over_display_name() -> None:
    renamed = _FakeDrive("Archive", url_name="Reports")
    reports = _FakeDrive("Reports", url_name="Reports2")
    connector = _build_connector([renamed, reports])

    result = connector._resolve_drive(_STRIPPED_URL_SITE, "Reports")

    assert result is not None
    assert result.drive_id == renamed.id
    assert result.display_name == "Archive"


def test_fetch_driveitems_matches_library_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _build_connector([_FakeDrive("Documents"), _STRIPPED_URL_DRIVE])
    monkeypatch.setattr(
        sp_connector, "iter_drive_items_delta", _fake_iter_drive_items_delta
    )

    results = list(connector._fetch_driveitems(site_descriptor=_STRIPPED_URL_SITE))

    assert [
        (result.drive.display_name, result.drive.web_url) for result in results
    ] == [("R&D Library", _STRIPPED_URL_DRIVE.web_url)]


def test_load_from_checkpoint_uses_display_name_for_library_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive nodes and documents carry the display name SharePoint list lookups need."""
    connector = _build_connector([_FakeDrive("Documents"), _STRIPPED_URL_DRIVE])
    connector.include_site_pages = False
    captured_drive_names: list[str] = []

    def fake_convert(
        driveitem: DriveItemData, drive: SiteDrive, *_: Any, **__: Any
    ) -> Document:
        captured_drive_names.append(drive.display_name)
        return Document(
            id=driveitem.id,
            source=DocumentSource.SHAREPOINT,
            semantic_identifier=driveitem.name,
            metadata={},
            sections=[TextSection(link="https://example.com", text="content")],
        )

    monkeypatch.setattr(
        sp_connector,
        "fetch_one_delta_page",
        lambda *_, **__: ([_SAMPLE_ITEM], None),
    )
    monkeypatch.setattr(
        sp_connector, "_convert_driveitem_to_document_with_permissions", fake_convert
    )
    monkeypatch.setattr(
        SharepointConnector, "_get_graph_access_token", lambda _self: "fake-token"
    )

    checkpoint = SharepointConnectorCheckpoint(has_more=True)
    checkpoint.cached_site_descriptors = deque()
    checkpoint.current_site_descriptor = _STRIPPED_URL_SITE
    checkpoint.legacy_cached_drive_names = deque(["RD Library"])
    checkpoint.process_site_pages = False

    yielded: list[Any] = []
    generator = connector._load_from_checkpoint(
        start=0, end=0, checkpoint=checkpoint, include_permissions=False
    )
    try:
        while True:
            yielded.append(next(generator))
    except StopIteration:
        pass

    drive_nodes = [
        item
        for item in yielded
        if isinstance(item, HierarchyNode) and item.node_type == HierarchyNodeType.DRIVE
    ]
    assert [node.display_name for node in drive_nodes] == ["R&D Library"]
    assert captured_drive_names == ["R&D Library"]


def test_fetch_driveitems_uses_delta_when_no_folder_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When folder_path is None, _fetch_driveitems should use delta."""
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
        folder_id: str | None = None,  # noqa: ARG001
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        called_method.append("paged")
        yield _SAMPLE_ITEM

    monkeypatch.setattr(sp_connector, "iter_drive_items_delta", fake_delta)
    monkeypatch.setattr(sp_connector, "iter_drive_items_paged", fake_paged)

    list(connector._fetch_driveitems(site))

    assert called_method == ["delta"]


def test_fetch_driveitems_uses_paged_when_folder_path_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When folder_path is set, _fetch_driveitems should use BFS."""
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
        folder_id: str | None = None,  # noqa: ARG001
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        called_method.append("paged")
        yield _SAMPLE_ITEM

    monkeypatch.setattr(sp_connector, "iter_drive_items_delta", fake_delta)
    monkeypatch.setattr(sp_connector, "iter_drive_items_paged", fake_paged)
    monkeypatch.setattr(
        sp_connector,
        "resolve_drive_folder",
        lambda *_args, **_kwargs: DriveFolderReference(
            id="folder-id",
            web_url="https://example.sharepoint.com/sites/sample/Engineering/Docs",
        ),
    )

    list(connector._fetch_driveitems(site))

    assert called_method == ["paged"]


# _fetch_driveitems refusal handling. This is the slim path: its callers delete
# or lock out whatever a run did not reach, so a swallowed error costs a site.


def _graph_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(response=response)


def _sdk_error(status_code: int) -> ClientRequestException:
    response = Response()
    response.status_code = status_code
    return ClientRequestException(f"{status_code} Client Error", response=response)


class _RefusingSites:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def get_by_url(self, _url: str) -> NoReturn:
        raise self._error


class _RefusingGraphClient:
    def __init__(self, error: Exception) -> None:
        self.sites = _RefusingSites(error)


def _site() -> SiteDescriptor:
    return SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name=None,
        folder_path=None,
    )


def _connector_whose_site_lookup_raises(error: Exception) -> SharepointConnector:
    connector = SharepointConnector()
    connector._graph_client = _RefusingGraphClient(error)  # ty: ignore[invalid-assignment]
    return connector


@pytest.mark.parametrize("status_code", [403, 404, 423])
def test_fetch_driveitems_leaves_out_a_site_graph_refuses_for_good(
    status_code: int,
) -> None:
    connector = _connector_whose_site_lookup_raises(_sdk_error(status_code))

    assert list(connector._fetch_driveitems(_site())) == []


@pytest.mark.parametrize(
    "error",
    [_sdk_error(401), _sdk_error(503), requests.ConnectionError("reset")],
    ids=["401", "503", "transport"],
)
def test_fetch_driveitems_raises_when_the_site_lookup_fails_otherwise(
    error: Exception,
) -> None:
    connector = _connector_whose_site_lookup_raises(error)

    with pytest.raises(type(error)):
        list(connector._fetch_driveitems(_site()))


def _delta_that_raises(
    error: Exception,
) -> Callable[..., Generator[DriveItemData, None, None]]:
    def fake_delta(
        client: GraphApiClient,  # noqa: ARG001
        drive_id: str,
        start: datetime | None = None,  # noqa: ARG001
        end: datetime | None = None,  # noqa: ARG001
        page_size: int = 200,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        if drive_id == "fake-drive-id-Refused":
            raise error
        yield _SAMPLE_ITEM

    return fake_delta


@pytest.mark.parametrize("status_code", [404, 423, 401, 500])
def test_fetch_driveitems_raises_when_a_drive_fails(
    status_code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A drive error is never a skip: the walk has already answered for the
    site, and files counted so far cannot tell a refused drive from a refused
    page, so the slim callers would prune what the walk did not reach."""
    connector = _build_connector([_FakeDrive("Refused"), _FakeDrive("Readable")])
    monkeypatch.setattr(
        sp_connector,
        "iter_drive_items_delta",
        _delta_that_raises(_graph_error(status_code)),
    )

    with pytest.raises(HTTPError):
        list(connector._fetch_driveitems(_site()))
