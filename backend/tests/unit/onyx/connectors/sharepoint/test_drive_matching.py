from collections import deque
from collections.abc import Callable, Generator, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import quote

import pytest

from onyx.connectors.microsoft_utils.drive_delta import (
    DriveDeltaFetchResult,
    DriveDeltaPage,
    parse_graph_sharepoint_ids,
)
from onyx.connectors.microsoft_utils.drive_items import (
    DriveFolderReference,
    DriveItemData,
)
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.models import (
    Document,
    DocumentSource,
    HierarchyNode,
    TextSection,
)
from onyx.connectors.sharepoint import connector as sp_connector
from onyx.connectors.sharepoint.connector import (
    SHARED_DOCUMENTS_MAP,
    SharepointConnector,
    SharepointConnectorCheckpoint,
    SiteDescriptor,
    SiteDrive,
)
from onyx.connectors.sharepoint.models import SharepointDrive
from onyx.db.enums import HierarchyNodeType
from tests.unit.onyx.connectors.sharepoint.sharepoint_gateway_fakes import (
    connector_with_gateway,
    stub_operation,
)


def _drive(
    name: str,
    drive_type: str | None = None,
    url_name: str | None = None,
    list_id: str | None = None,
    with_list: bool = True,
) -> SharepointDrive:
    return SharepointDrive(
        id=f"fake-drive-id-{name}",
        name=name,
        web_url=f"https://example.sharepoint.com/sites/sample/{quote(url_name or name)}",
        drive_type=drive_type,
        list_id=(list_id or f"list-id-{name}") if with_list else None,
    )


_SAMPLE_ITEM = DriveItemData(
    id="item-1",
    name="sample.pdf",
    web_url="https://example.sharepoint.com/sites/sample/sample.pdf",
    parent_reference_path=None,
    drive_id="fake-drive-id",
)


def _delta_fetch_result(item: DriveItemData) -> DriveDeltaFetchResult:
    page = DriveDeltaPage.model_validate(
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
    return DriveDeltaFetchResult(page=page)


def _build_connector(drives: Sequence[SharepointDrive]) -> SharepointConnector:
    connector = SharepointConnector()
    gateway = connector_with_gateway(connector)
    stub_operation(gateway, "list_drives", lambda *, site_url: list(drives))  # noqa: ARG005
    return connector


def _fake_iter_delta_items(
    *,
    drive_id: str,  # noqa: ARG001
    start: datetime | None,  # noqa: ARG001
    end: datetime | None,  # noqa: ARG001
) -> Generator[DriveItemData, None, None]:
    yield _SAMPLE_ITEM


def _fake_get_delta_page(
    *,
    drive_id: str,  # noqa: ARG001
    page_url: str,  # noqa: ARG001
    allow_full_resync: bool,  # noqa: ARG001
) -> DriveDeltaFetchResult:
    return _delta_fetch_result(_SAMPLE_ITEM)


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
) -> None:
    connector = _build_connector(
        [_drive(graph_drive_name, url_name=requested_drive_name)]
    )
    site_descriptor = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name=requested_drive_name,
        folder_path=None,
    )
    stub_operation(connector.ops, "iter_delta_items", _fake_iter_delta_items)

    results = list(connector._fetch_driveitems(site_descriptor=site_descriptor))

    assert len(results) == 1
    assert results[0].driveitem.id == _SAMPLE_ITEM.id
    assert results[0].drive.display_name == requested_drive_name
    assert results[0].drive.web_url is not None


def test_fetch_driveitems_uses_drive_id_without_list_id() -> None:
    drive = _drive("System", with_list=False)
    connector = _build_connector([drive])
    traversed_drive_ids: list[str] = []

    def fake_delta(
        *,
        drive_id: str,
        start: datetime | None,  # noqa: ARG001
        end: datetime | None,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        traversed_drive_ids.append(drive_id)
        yield _SAMPLE_ITEM

    stub_operation(connector.ops, "iter_delta_items", fake_delta)

    results = list(connector._fetch_driveitems(site_descriptor=_site()))

    assert traversed_drive_ids == [drive.id]
    assert results[0].drive.list_id is None


def test_load_from_checkpoint_maps_drive_name(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _build_connector([_drive("Documents")])
    connector.include_site_pages = False

    captured_drive_names: list[str] = []

    def fake_convert(
        driveitem: DriveItemData,  # noqa: ARG001
        drive: SiteDrive,
        ops: Any,  # noqa: ARG001
        site_url: str,  # noqa: ARG001
        include_permissions: bool = False,  # noqa: ARG001
        parent_hierarchy_raw_node_id: str | None = None,  # noqa: ARG001
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

    stub_operation(connector.ops, "get_delta_page", _fake_get_delta_page)
    monkeypatch.setattr(
        sp_connector, "_convert_driveitem_to_document_with_permissions", fake_convert
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

    all_yielded = list(
        connector._load_from_checkpoint(
            start=0, end=0, checkpoint=checkpoint, include_permissions=False
        )
    )

    documents = [item for item in all_yielded if not isinstance(item, HierarchyNode)]
    hierarchy_nodes = [item for item in all_yielded if isinstance(item, HierarchyNode)]

    assert len(documents) == 1
    assert captured_drive_names == ["Shared Documents"]
    assert len(hierarchy_nodes) >= 1


def test_deleted_legacy_current_drive_preserves_queue_after_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remaining = _drive("Remaining")
    connector = _build_connector([remaining])
    connector.include_site_pages = False
    stub_operation(connector.ops, "get_delta_page", _fake_get_delta_page)
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


def _resolve_personal(drives: list[SharepointDrive]) -> SiteDrive | None:
    connector = _build_connector(drives)
    site_descriptor = SiteDescriptor(
        url=_PERSONAL_SITE_URL,
        drive_name="Documents",
        folder_path=None,
    )
    return connector._resolve_drive(site_descriptor, "Documents")


def test_resolve_drive_personal_picks_by_drive_type_not_position() -> None:
    """The user's OneDrive must be selected by driveType regardless of order."""
    extra_library = _drive("Extra Library", drive_type="documentLibrary")
    onedrive = _drive("OneDrive", drive_type="business")

    # OneDrive is second in the (unordered) response; positional selection would
    # have picked the wrong library.
    result = _resolve_personal([extra_library, onedrive])

    assert result is not None
    assert result.drive_id == onedrive.id


def test_resolve_drive_personal_selects_url_segment_between_business_drives() -> None:
    onedrive = _drive("OneDrive", drive_type="business", url_name="Documents")
    cache = _drive(
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
    extra_library = _drive("Extra Library", drive_type="documentLibrary")
    onedrive = _drive("OneDrive", drive_type=None)

    result = _resolve_personal([extra_library, onedrive])

    assert result is None


def test_resolve_drive_personal_prefers_type_over_name_collision() -> None:
    """A uniquely-typed primary drive wins even if another library reuses a name."""
    # Localized primary drive name so resolution must rely on driveType.
    primary = _drive("Mon lecteur OneDrive", drive_type="business")
    # An extra library that happens to carry a fallback OneDrive name but is not
    # the user's primary drive.
    extra_library = _drive("OneDrive", drive_type="documentLibrary")

    result = _resolve_personal([extra_library, primary])

    assert result is not None
    assert result.drive_id == primary.id


def test_resolve_drive_personal_ambiguous_raises() -> None:
    """Refuse to guess when multiple primary-OneDrive candidates exist."""
    first = _drive("OneDrive", drive_type="business")
    second = _drive("Second OneDrive", drive_type="personal")

    with pytest.raises(ValueError, match="unambiguously"):
        _resolve_personal([first, second])


# SharePoint strips "&" from the library URL, so "R&D Library" lives at "RD Library".
_STRIPPED_URL_DRIVE = _drive("R&D Library", url_name="RD Library")
_DOCUMENTS_SITE = SiteDescriptor(
    url="https://example.sharepoint.com/sites/sample",
    drive_name="Documents",
    folder_path=None,
)
_BARE_SITE = SiteDescriptor(
    url="https://example.sharepoint.com/sites/sample",
    drive_name=None,
    folder_path=None,
)
_STRIPPED_URL_SITE = SiteDescriptor(
    url="https://example.sharepoint.com/sites/sample",
    drive_name="RD Library",
    folder_path=None,
)


def test_resolve_drive_ignores_unrelated_libraries_without_metadata() -> None:
    bare = SharepointDrive(id="bare-drive")
    connector = _build_connector([bare, _drive("Documents")])

    result = connector._resolve_drive(_DOCUMENTS_SITE, "Documents")

    assert result is not None
    assert result.drive_id == "fake-drive-id-Documents"


def test_resolve_drive_requires_metadata_on_the_selected_library() -> None:
    bare = SharepointDrive(id="bare-drive", name="Documents")
    connector = _build_connector([bare])

    with pytest.raises(ValueError, match="traversal metadata"):
        connector._fetch_driveitems(_BARE_SITE).__next__()


def test_resolve_drive_matches_library_url_and_returns_display_name() -> None:
    connector = _build_connector([_drive("Documents"), _STRIPPED_URL_DRIVE])

    result = connector._resolve_drive(_STRIPPED_URL_SITE, "RD Library")

    assert result is not None
    assert result.drive_id == _STRIPPED_URL_DRIVE.id
    assert result.display_name == "R&D Library"


def test_graph_sharepoint_ids_parser_reads_valid_facet() -> None:
    result = parse_graph_sharepoint_ids({"listId": "list-id"})

    assert result is not None
    assert result.list_id == "list-id"


@pytest.mark.parametrize("value", [None, "invalid", []])
def test_graph_sharepoint_ids_parser_ignores_non_dict_facets(value: object) -> None:
    assert parse_graph_sharepoint_ids(value) is None


def test_graph_sharepoint_ids_parser_rejects_malformed_dict() -> None:
    with pytest.raises(ValueError):
        parse_graph_sharepoint_ids({"listId": {"unexpected": "object"}})


def test_resolve_drive_prefers_library_url_over_display_name() -> None:
    renamed = _drive("Archive", url_name="Reports")
    reports = _drive("Reports", url_name="Reports2")
    connector = _build_connector([renamed, reports])

    result = connector._resolve_drive(_STRIPPED_URL_SITE, "Reports")

    assert result is not None
    assert result.drive_id == renamed.id
    assert result.display_name == "Archive"


def test_fetch_driveitems_matches_library_url() -> None:
    connector = _build_connector([_drive("Documents"), _STRIPPED_URL_DRIVE])
    stub_operation(connector.ops, "iter_delta_items", _fake_iter_delta_items)

    results = list(connector._fetch_driveitems(site_descriptor=_STRIPPED_URL_SITE))

    assert [
        (result.drive.display_name, result.drive.web_url) for result in results
    ] == [("R&D Library", _STRIPPED_URL_DRIVE.web_url)]


def test_load_from_checkpoint_uses_display_name_for_library_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive nodes and documents carry the display name SharePoint list lookups need."""
    connector = _build_connector([_drive("Documents"), _STRIPPED_URL_DRIVE])
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

    stub_operation(connector.ops, "get_delta_page", _fake_get_delta_page)
    monkeypatch.setattr(
        sp_connector, "_convert_driveitem_to_document_with_permissions", fake_convert
    )

    checkpoint = SharepointConnectorCheckpoint(has_more=True)
    checkpoint.cached_site_descriptors = deque()
    checkpoint.current_site_descriptor = _STRIPPED_URL_SITE
    checkpoint.legacy_cached_drive_names = deque(["RD Library"])
    checkpoint.process_site_pages = False

    yielded = list(
        connector._load_from_checkpoint(
            start=0, end=0, checkpoint=checkpoint, include_permissions=False
        )
    )

    drive_nodes = [
        item
        for item in yielded
        if isinstance(item, HierarchyNode) and item.node_type == HierarchyNodeType.DRIVE
    ]
    assert [node.display_name for node in drive_nodes] == ["R&D Library"]
    assert captured_drive_names == ["R&D Library"]


def _recording_walkers(
    called_method: list[str],
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    def fake_delta(
        *,
        drive_id: str,  # noqa: ARG001
        start: datetime | None,  # noqa: ARG001
        end: datetime | None,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        called_method.append("delta")
        yield _SAMPLE_ITEM

    def fake_folder(
        *,
        drive_id: str,  # noqa: ARG001
        folder_id: str | None,  # noqa: ARG001
        start: datetime | None,  # noqa: ARG001
        end: datetime | None,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        called_method.append("paged")
        yield _SAMPLE_ITEM

    return fake_delta, fake_folder


def test_fetch_driveitems_uses_delta_when_no_folder_path() -> None:
    """When folder_path is None, _fetch_driveitems should use delta."""
    connector = _build_connector([_drive("Documents")])
    site = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name="Documents",
        folder_path=None,
    )
    called_method: list[str] = []
    fake_delta, fake_folder = _recording_walkers(called_method)
    stub_operation(connector.ops, "iter_delta_items", fake_delta)
    stub_operation(connector.ops, "iter_folder_items", fake_folder)

    list(connector._fetch_driveitems(site))

    assert called_method == ["delta"]


def test_fetch_driveitems_uses_paged_when_folder_path_set() -> None:
    """When folder_path is set, _fetch_driveitems should use BFS."""
    connector = _build_connector([_drive("Documents")])
    site = SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name="Documents",
        folder_path="Engineering/Docs",
    )
    called_method: list[str] = []
    fake_delta, fake_folder = _recording_walkers(called_method)
    stub_operation(connector.ops, "iter_delta_items", fake_delta)
    stub_operation(connector.ops, "iter_folder_items", fake_folder)
    stub_operation(
        connector.ops,
        "resolve_folder",
        lambda *, drive_id, folder_path: DriveFolderReference(  # noqa: ARG005
            id="folder-id",
            web_url="https://example.sharepoint.com/sites/sample/Engineering/Docs",
        ),
    )

    list(connector._fetch_driveitems(site))

    assert called_method == ["paged"]


# _fetch_driveitems refusal handling. This is the slim path: its callers delete
# or lock out whatever a run did not reach, so a swallowed error costs a site.


def _site() -> SiteDescriptor:
    return SiteDescriptor(
        url="https://example.sharepoint.com/sites/sample",
        drive_name=None,
        folder_path=None,
    )


def _connector_whose_site_lookup_raises(error: Exception) -> SharepointConnector:
    connector = SharepointConnector()
    gateway = connector_with_gateway(connector)

    def refuse(*, site_url: str) -> list[SharepointDrive]:  # noqa: ARG001
        raise error

    stub_operation(gateway, "list_drives", refuse)
    return connector


@pytest.mark.parametrize("status_code", [403, 404, 423])
def test_fetch_driveitems_leaves_out_a_site_graph_refuses_for_good(
    status_code: int,
) -> None:
    connector = _connector_whose_site_lookup_raises(
        MicrosoftGraphError(status_code, "accessDenied", "refused")
    )

    assert list(connector._fetch_driveitems(_site())) == []


@pytest.mark.parametrize(
    "error",
    [
        MicrosoftGraphError(401, "accessDenied", "refused"),
        MicrosoftGraphError(503, "accessDenied", "refused"),
        MicrosoftGraphError(None, "ConnectionError", "reset"),
    ],
    ids=["401", "503", "transport"],
)
def test_fetch_driveitems_raises_when_the_site_lookup_fails_otherwise(
    error: MicrosoftGraphError,
) -> None:
    connector = _connector_whose_site_lookup_raises(error)

    with pytest.raises(MicrosoftGraphError):
        list(connector._fetch_driveitems(_site()))


def _delta_that_raises(
    error: Exception,
) -> Callable[..., Generator[DriveItemData, None, None]]:
    def fake_delta(
        *,
        drive_id: str,
        start: datetime | None,  # noqa: ARG001
        end: datetime | None,  # noqa: ARG001
    ) -> Generator[DriveItemData, None, None]:
        if drive_id == "fake-drive-id-Refused":
            raise error
        yield _SAMPLE_ITEM

    return fake_delta


@pytest.mark.parametrize("status_code", [404, 423, 401, 500])
def test_fetch_driveitems_raises_when_a_drive_fails(status_code: int) -> None:
    """A drive error is never a skip: the walk has already answered for the
    site, and files counted so far cannot tell a refused drive from a refused
    page, so the slim callers would prune what the walk did not reach."""
    connector = _build_connector([_drive("Refused"), _drive("Readable")])
    stub_operation(
        connector.ops,
        "iter_delta_items",
        _delta_that_raises(MicrosoftGraphError(status_code, "accessDenied", "refused")),
    )

    with pytest.raises(MicrosoftGraphError):
        list(connector._fetch_driveitems(_site()))
