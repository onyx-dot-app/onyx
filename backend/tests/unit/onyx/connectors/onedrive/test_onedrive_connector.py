import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from ee.onyx.external_permissions.onedrive.permission_mapper import (
    map_onedrive_permissions,
)
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import CapabilityCheckContext
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.microsoft_utils.drive_delta import (
    DEFAULT_DRIVE_DELTA_PAGE_SIZE,
    DriveDeltaItem,
    DriveDeltaPage,
)
from onyx.connectors.microsoft_utils.drive_items import DriveItemContent, DriveItemData
from onyx.connectors.microsoft_utils.graph_errors import (
    MISSING_CREDENTIAL_CODE,
    raise_for_auth_error,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError as OneDriveAuthError,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OneDriveGraphError,
)
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.connectors.onedrive.capability_checks import (
    build_onedrive_doc_permission_sync_checks,
    build_onedrive_group_sync_checks,
    build_onedrive_indexing_checks,
)
from onyx.connectors.onedrive.connector import (
    MAX_DRIVE_DELTA_PAGES,
    MAX_USER_LISTING_PAGES,
    OneDriveConnector,
    drive_item_document,
    drive_root_id,
    folder_node,
    hierarchy_item_id,
)
from onyx.connectors.onedrive.models import (
    OneDriveCheckpoint,
    OneDriveDeltaResult,
    OneDriveDrive,
    OneDriveGroup,
    OneDriveGroupMemberPage,
    OneDriveGroupPage,
    OneDrivePermissionPage,
    OneDriveUser,
    OneDriveUserPage,
)
from onyx.connectors.onedrive.scope import normalize_configured_users
from onyx.connectors.onedrive.source_operations import OneDriveSourceOperations
from onyx.connectors.registry import CONNECTOR_CLASS_MAP

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tenant_spike.json"


def _run_step(
    connector: OneDriveConnector,
    checkpoint: OneDriveCheckpoint,
    start: float = 0,
    end: float = 2_000_000_000,
) -> tuple[list[Document | HierarchyNode | ConnectorFailure], OneDriveCheckpoint]:
    generator = connector.load_from_checkpoint(start, end, checkpoint)
    output: list[Document | HierarchyNode | ConnectorFailure] = []
    while True:
        try:
            output.append(next(generator))
        except StopIteration as stop:
            return output, stop.value


def _run_perm_step(
    connector: OneDriveConnector,
    checkpoint: OneDriveCheckpoint,
) -> tuple[list[Document | HierarchyNode | ConnectorFailure], OneDriveCheckpoint]:
    generator = connector.load_from_checkpoint_with_perm_sync(
        0, 2_000_000_000, checkpoint
    )
    output: list[Document | HierarchyNode | ConnectorFailure] = []
    while True:
        try:
            output.append(next(generator))
        except StopIteration as stop:
            return output, stop.value


def _fixture_payload() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text())


def _fixture_item(item_id: str, section: str) -> DriveDeltaItem:
    payload = _fixture_payload()
    raw_item = next(
        item
        for page in payload[section]
        for item in page["value"]
        if item["id"] == item_id
    )
    normalized_item = dict(raw_item)
    for field in ("createdDateTime", "lastModifiedDateTime"):
        if normalized_item.get(field) == "<timestamp>":
            normalized_item[field] = "2026-01-01T00:00:00Z"
    return DriveDeltaItem.model_validate(normalized_item)


def _fixture_permissions(shape: str) -> OneDrivePermissionPage:
    payload = _fixture_payload()["permission_shapes"][shape]
    return OneDrivePermissionPage.model_validate({"permissions": payload["value"]})


def _user(name: str = "owner@example.com") -> OneDriveUser:
    return OneDriveUser(id=f"id-{name}", user_principal_name=name, display_name=name)


def _drive() -> OneDriveDrive:
    return OneDriveDrive(id="drive-1", name="Documents")


def _connector(*, users: list[str] | None = None) -> tuple[OneDriveConnector, Any]:
    connector = OneDriveConnector(users=users)
    gateway = create_autospec(OneDriveSourceOperations, instance=True)
    connector._ops = gateway
    return connector, gateway


def _file_item() -> DriveDeltaItem:
    return DriveDeltaItem.model_validate(
        {
            "id": "raw-item-id",
            "name": "report.txt",
            "webUrl": "https://example.test/report.txt",
            "size": 4,
            "file": {"mimeType": "text/plain"},
            "createdDateTime": "2026-01-01T00:00:00Z",
            "lastModifiedDateTime": "2026-01-02T00:00:00Z",
            "parentReference": {
                "driveId": "drive-1",
                "id": "folder-1",
                "path": "/drives/drive-1/root:/Folder",
            },
        }
    )


def _folder_item() -> DriveDeltaItem:
    return DriveDeltaItem.model_validate(
        {
            "id": "folder-1",
            "name": "Folder",
            "folder": {"childCount": 1},
            "parentReference": {
                "driveId": "drive-1",
                "id": "root-id",
                "path": "/drives/drive-1/root:",
            },
        }
    )


def test_onedrive_scope_is_ordered_normalized_and_deduplicated() -> None:
    assert normalize_configured_users(
        [" First@Example.com ", "", "second@example.com", "first@example.com"]
    ) == ["first@example.com", "second@example.com"]
    with pytest.raises(ConnectorValidationError):
        normalize_configured_users(["not-an-email"])
    with pytest.raises(ConnectorValidationError, match="at least one email"):
        normalize_configured_users([" ", ""])


def test_onedrive_preserves_organization_link_setting() -> None:
    connector: OneDriveConnector = OneDriveConnector(
        treat_organization_link_as_public=True
    )

    assert connector.settings.treat_organization_link_as_public


def test_onedrive_credential_validation_error_does_not_expose_input() -> None:
    secret = "do-not-expose"
    error = OneDriveAuthError(MISSING_CREDENTIAL_CODE, secret)

    with pytest.raises(CredentialInvalidError) as raised:
        raise_for_auth_error(error)

    assert secret not in str(raised.value)


def test_onedrive_uses_shared_national_cloud_pair_validation() -> None:
    OneDriveConnector(
        graph_api_host="https://graph.microsoft.us",
        authority_host="https://login.microsoftonline.us",
    )
    with pytest.raises(ConnectorValidationError):
        OneDriveConnector(
            graph_api_host="https://graph.microsoft.us",
            authority_host="https://login.microsoftonline.com",
        )


def test_onedrive_checkpoint_opens_first_delta_in_one_step() -> None:
    connector, gateway = _connector()
    first = _user()
    second = _user("second@example.com")
    gateway.list_users.return_value = OneDriveUserPage(
        users=[first, second], next_link="users-next"
    )
    gateway.get_default_drive.return_value = _drive()
    gateway.get_delta_page.return_value = OneDriveDeltaResult(
        page=DriveDeltaPage(), next_cursor="delta-next"
    )
    checkpoint = connector.build_dummy_checkpoint()

    output, checkpoint = _run_step(connector, checkpoint)
    assert [type(item) for item in output] == [HierarchyNode]
    assert checkpoint.current_user == first
    assert checkpoint.current_drive == _drive()
    assert checkpoint.user_page == [second]
    gateway.get_default_drive.assert_called_once()
    assert checkpoint.delta_cursor == "delta-next"
    gateway.get_delta_page.assert_called_once()

    gateway.get_delta_page.reset_mock()
    gateway.get_delta_page.return_value = OneDriveDeltaResult(page=DriveDeltaPage())
    _, checkpoint = _run_step(connector, checkpoint)
    assert checkpoint.current_user is None
    assert checkpoint.user_page == [second]
    gateway.get_delta_page.assert_called_once()
    assert gateway.get_delta_page.call_args.kwargs["page_url"] == "delta-next"


def test_onedrive_new_attempt_uses_fixed_delta_page_size() -> None:
    connector, gateway = _connector(users=["owner@example.com"])
    gateway.get_user.return_value = _user()
    gateway.get_default_drive.return_value = _drive()
    gateway.get_delta_page.return_value = OneDriveDeltaResult(page=DriveDeltaPage())
    checkpoint = connector.build_dummy_checkpoint()
    _run_step(connector, checkpoint, start=10)

    page_url = gateway.get_delta_page.call_args.kwargs["page_url"]
    assert f"$top={DEFAULT_DRIVE_DELTA_PAGE_SIZE}" in page_url
    assert "$select=" in page_url
    assert "token=1970-01-01T00%3A00%3A10%2B00%3A00" in page_url
    assert (
        gateway.get_delta_page.call_args.kwargs["page_size"]
        == DEFAULT_DRIVE_DELTA_PAGE_SIZE
    )


def test_onedrive_explicit_user_failure_is_reported() -> None:
    connector, gateway = _connector(users=["missing@example.com"])
    gateway.get_user.return_value = None

    output, checkpoint = _run_step(connector, connector.build_dummy_checkpoint())

    assert len(output) == 1
    assert isinstance(output[0], ConnectorFailure)
    assert output[0].failed_entity is not None
    assert output[0].failed_entity.entity_id == "drive:missing@example.com"
    assert checkpoint.configured_user_index == 1


def test_onedrive_discovered_missing_drive_is_skipped() -> None:
    connector, gateway = _connector()
    gateway.list_users.return_value = OneDriveUserPage(users=[_user()])
    gateway.get_default_drive.return_value = None

    output, checkpoint = _run_step(connector, connector.build_dummy_checkpoint())

    assert output == []
    assert checkpoint.current_user is None


def test_onedrive_all_user_drive_denial_skips_but_transient_error_retries() -> None:
    connector, gateway = _connector()
    checkpoint = OneDriveCheckpoint(has_more=True, current_user=_user())
    gateway.get_default_drive.side_effect = OneDriveGraphError(
        403, "accessDenied", "not selected"
    )

    output, checkpoint = _run_step(connector, checkpoint)

    assert len(output) == 1
    assert isinstance(output[0], ConnectorFailure)
    assert checkpoint.current_user is None

    checkpoint.current_user = _user()
    gateway.get_default_drive.side_effect = OneDriveGraphError(
        429, "throttledRequest", "retry"
    )
    with pytest.raises(OneDriveGraphError):
        _run_step(connector, checkpoint)
    assert checkpoint.current_user is not None


def test_onedrive_explicit_drive_denial_yields_failure() -> None:
    connector, gateway = _connector(users=["owner@example.com"])
    checkpoint = OneDriveCheckpoint(has_more=True, current_user=_user())
    gateway.get_default_drive.side_effect = OneDriveGraphError(
        403, "accessDenied", "denied"
    )

    output, checkpoint = _run_step(connector, checkpoint)

    assert len(output) == 1
    assert isinstance(output[0], ConnectorFailure)
    assert checkpoint.current_user is None


@pytest.mark.parametrize("status", [400, 401])
def test_onedrive_systemic_graph_errors_propagate(status: int) -> None:
    error = OneDriveGraphError(status, "systemicError", "stop")
    connector, gateway = _connector()
    gateway.get_default_drive.side_effect = error
    drive_checkpoint = OneDriveCheckpoint(has_more=True, current_user=_user())

    with pytest.raises(OneDriveGraphError):
        _run_step(connector, drive_checkpoint)

    gateway.get_delta_page.side_effect = error
    delta_checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
    )

    with pytest.raises(OneDriveGraphError):
        _run_step(connector, delta_checkpoint)


def test_onedrive_checkpoint_bounds_external_pagination() -> None:
    connector, gateway = _connector()
    user_checkpoint = OneDriveCheckpoint(
        has_more=True,
        user_listing_pages=MAX_USER_LISTING_PAGES,
    )

    with pytest.raises(RuntimeError, match="user listing exceeded"):
        _run_step(connector, user_checkpoint)
    gateway.list_users.assert_not_called()

    delta_checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
        delta_pages=MAX_DRIVE_DELTA_PAGES,
    )
    with pytest.raises(RuntimeError, match="delta exceeded"):
        _run_step(connector, delta_checkpoint)
    gateway.get_delta_page.assert_not_called()


def test_onedrive_checkpoint_emits_later_occurrences_across_pages() -> None:
    connector, gateway = _connector()
    item = _file_item()
    folder = _folder_item()
    gateway.download_item.return_value = DriveItemContent(
        sections=[TextSection(text="body")]
    )
    gateway.get_delta_page.side_effect = [
        OneDriveDeltaResult(
            page=DriveDeltaPage(items=[folder, item]),
            next_cursor="next",
        ),
        OneDriveDeltaResult(page=DriveDeltaPage(items=[folder, item])),
    ]
    checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
    )

    first_output, checkpoint = _run_step(connector, checkpoint)

    assert len(first_output) == 3
    checkpoint = connector.validate_checkpoint_json(checkpoint.model_dump_json())

    second_output, checkpoint = _run_step(connector, checkpoint)

    assert [type(item) for item in second_output] == [HierarchyNode, Document]
    assert checkpoint.current_user is None
    assert gateway.download_item.call_count == 2


def test_onedrive_delta_page_keeps_last_occurrence_order() -> None:
    connector, gateway = _connector()
    old_item = _file_item()
    latest_item = old_item.model_copy(update={"name": "latest.txt"})
    gateway.download_item.return_value = DriveItemContent(
        sections=[TextSection(text="body")]
    )
    gateway.get_delta_page.return_value = OneDriveDeltaResult(
        page=DriveDeltaPage(items=[old_item, _folder_item(), latest_item])
    )
    checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
    )

    output, _ = _run_step(connector, checkpoint)

    assert [type(item) for item in output] == [
        HierarchyNode,
        HierarchyNode,
        Document,
    ]
    document = output[-1]
    assert isinstance(document, Document)
    assert document.semantic_identifier == "latest.txt"
    gateway.download_item.assert_called_once()


def test_onedrive_checkpoint_repeats_refresh_latest_acl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector, gateway = _connector()
    first_access = ExternalAccess(
        external_user_emails={"first@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )
    latest_access = ExternalAccess(
        external_user_emails={"latest@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )
    mapper = MagicMock(side_effect=[first_access, latest_access])
    monkeypatch.setattr(
        "onyx.connectors.onedrive.connector.get_onedrive_external_access", mapper
    )
    item = DriveDeltaItem.model_validate(
        {**_file_item().to_graph_json(), "shared": {"scope": "users"}}
    )
    gateway.list_permissions.return_value = OneDrivePermissionPage(permissions=[])
    gateway.download_item.return_value = DriveItemContent(
        sections=[TextSection(text="body")]
    )
    gateway.get_delta_page.side_effect = [
        OneDriveDeltaResult(
            page=DriveDeltaPage(items=[item]),
            next_cursor="next-delta",
        ),
        OneDriveDeltaResult(page=DriveDeltaPage(items=[item])),
    ]
    checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
    )

    first_output, checkpoint = _run_perm_step(connector, checkpoint)
    checkpoint = connector.validate_checkpoint_json(checkpoint.model_dump_json())
    latest_output, _ = _run_perm_step(connector, checkpoint)

    first_document = next(item for item in first_output if isinstance(item, Document))
    latest_document = next(item for item in latest_output if isinstance(item, Document))
    assert first_document.external_access == first_access
    assert latest_document.external_access == latest_access
    assert gateway.list_permissions.call_count == 2


def test_onedrive_delta_denial_skips_discovered_drive_and_reports_explicit_user() -> (
    None
):
    error = OneDriveGraphError(403, "accessDenied", "not selected")
    discovered, discovered_gateway = _connector()
    discovered_gateway.get_delta_page.side_effect = error
    discovered_checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
    )

    output, discovered_checkpoint = _run_step(discovered, discovered_checkpoint)

    assert len(output) == 1
    assert isinstance(output[0], ConnectorFailure)
    assert discovered_checkpoint.current_user is None

    explicit, explicit_gateway = _connector(users=["owner@example.com"])
    explicit_gateway.get_delta_page.side_effect = error
    explicit_checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
    )

    output, explicit_checkpoint = _run_step(explicit, explicit_checkpoint)

    assert len(output) == 1
    assert isinstance(output[0], ConnectorFailure)
    assert explicit_checkpoint.current_user is None


def test_onedrive_excluded_paths_drop_folders_and_files() -> None:
    connector, gateway = _connector()
    connector.settings = connector.settings.model_copy(
        update={"excluded_paths": ["Folder*"]}
    )
    gateway.get_delta_page.return_value = OneDriveDeltaResult(
        page=DriveDeltaPage(items=[_folder_item(), _file_item()])
    )
    checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
    )

    output, _ = _run_step(connector, checkpoint)

    assert len(output) == 1
    assert isinstance(output[0], HierarchyNode)
    assert output[0].raw_node_id == "drive-1:root"
    gateway.download_item.assert_not_called()


def test_onedrive_document_keeps_raw_graph_identity_and_scoped_hierarchy() -> None:
    item = _file_item()
    graph_item = item.to_graph_json()
    parsed = DriveItemData.from_graph_json(graph_item)
    document = drive_item_document(
        parsed,
        _drive(),
        DriveItemContent(sections=[TextSection(link=item.web_url, text="body")]),
        hierarchy_item_id("drive-1", "folder-1"),
    )

    assert graph_item["id"] == document.id == "raw-item-id"
    assert document.parent_hierarchy_raw_node_id == "drive-1:folder-1"
    assert document.external_access is not None
    assert not document.external_access.is_public


def test_onedrive_hierarchy_is_drive_scoped_and_private_in_ce() -> None:
    folder = DriveDeltaItem.model_validate(
        {
            "id": "folder",
            "name": "Folder",
            "folder": {"childCount": 1},
            "parentReference": {"id": "root-graph-id", "path": "/drives/d/root:"},
        }
    )
    node = folder_node(OneDriveDrive(id="d", name="Drive"), folder)

    assert node.raw_node_id == "d:folder"
    assert node.raw_parent_id == drive_root_id("d")
    assert node.external_access is not None
    assert node.external_access == node.external_access.empty()


def test_onedrive_recorded_spike_item_does_not_require_shared_changed() -> None:
    payload = json.loads(FIXTURE_PATH.read_text())
    full_items = [
        item for page in payload["full_delta_pages"] for item in page["value"]
    ]
    incremental_items = [
        item for page in payload["incremental_delta_pages"] for item in page["value"]
    ]
    tombstones = [
        item for item in incremental_items if "deleted" in item or "@removed" in item
    ]
    assert payload["full_fixture_item_count"] == 35
    assert payload["incremental_fixture_item_count"] == 12
    observations = " ".join(payload["observations"])
    assert "Full delta returned 35 fixture items" in observations
    assert "Timestamp delta returned 12 fixture items" in observations
    assert len(tombstones) == 1
    assert all(
        "@microsoft.graph.sharedChanged" not in item for item in incremental_items
    )
    raw_item = next(item for item in full_items if item.get("id") == "<file-direct-id>")
    raw_item["createdDateTime"] = "2026-01-01T00:00:00Z"
    raw_item["lastModifiedDateTime"] = "2026-01-02T00:00:00Z"
    raw_item.pop("@microsoft.graph.sharedChanged", None)

    item = DriveDeltaItem.model_validate(raw_item)

    assert item.is_file
    assert item.shared_changed is None
    assert item.id == "<file-direct-id>"


def test_onedrive_fixture_permission_mutations_traverse_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector, gateway = _connector()
    monkeypatch.setattr(
        "onyx.connectors.onedrive.connector.get_onedrive_external_access",
        map_onedrive_permissions,
    )
    destination = _fixture_item(
        "<folder-move-destination-id>", "incremental_delta_pages"
    )
    moved = _fixture_item("<file-move-id>", "incremental_delta_pages")
    remove_share = _fixture_item("<file-remove-share-id>", "incremental_delta_pages")
    restore_inheritance = _fixture_item(
        "<file-restore-inheritance-id>", "incremental_delta_pages"
    )
    permission_shapes = {
        destination.id: "move_destination_after",
        remove_share.id: "remove_share_after",
        restore_inheritance.id: "restore_inheritance_after",
    }

    def list_permissions(
        *,
        drive_id: str,
        item_id: str,
        next_link: str | None,
    ) -> OneDrivePermissionPage:
        del drive_id, next_link
        return _fixture_permissions(permission_shapes[item_id])

    gateway.list_permissions.side_effect = list_permissions
    gateway.download_item.return_value = DriveItemContent(
        sections=[TextSection(text="body")]
    )
    gateway.get_delta_page.return_value = OneDriveDeltaResult(
        page=DriveDeltaPage(
            items=[destination, moved, remove_share, restore_inheritance]
        )
    )
    checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
    )

    output, _ = _run_perm_step(connector, checkpoint)

    documents = {item.id: item for item in output if isinstance(item, Document)}
    moved_access = documents[moved.id].external_access
    remove_share_access = documents[remove_share.id].external_access
    restored_access = documents[restore_inheritance.id].external_access
    assert moved_access is not None
    assert remove_share_access is not None
    assert restored_access is not None
    assert "<alternate-user-email>" in moved_access.external_user_emails
    assert remove_share_access.external_user_emails == {
        "owner@example.com",
        "<owner-email>",
    }
    assert "<primary-user-email>" in restored_access.external_user_emails
    permission_item_ids = [
        call.kwargs["item_id"] for call in gateway.list_permissions.call_args_list
    ]
    assert permission_item_ids == [
        destination.id,
        remove_share.id,
        restore_inheritance.id,
    ]


def test_onedrive_permission_pagination_rejects_page_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector, gateway = _connector()
    monkeypatch.setattr("onyx.connectors.onedrive.connector.MAX_PERMISSION_PAGES", 2)
    gateway.list_permissions.side_effect = [
        OneDrivePermissionPage(permissions=[], next_link="permissions-1"),
        OneDrivePermissionPage(permissions=[], next_link="permissions-2"),
    ]

    with pytest.raises(ValueError, match="permission page limit"):
        connector._list_all_permissions("drive", "item")

    assert gateway.list_permissions.call_count == 2


def test_onedrive_file_permission_transient_error_fails_attempt() -> None:
    connector, gateway = _connector()
    gateway.get_delta_page.return_value = OneDriveDeltaResult(
        page=DriveDeltaPage(items=[_file_item()])
    )
    gateway.list_permissions.side_effect = OneDriveGraphError(
        429, "tooManyRequests", "retry later"
    )
    checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
    )

    with pytest.raises(OneDriveGraphError, match="tooManyRequests"):
        _run_perm_step(connector, checkpoint)


def test_onedrive_slim_folder_access_prefixes_external_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector, gateway = _connector()
    monkeypatch.setattr(
        "onyx.connectors.onedrive.connector.get_onedrive_external_access",
        map_onedrive_permissions,
    )
    folder = _folder_item()
    gateway.get_delta_page.return_value = OneDriveDeltaResult(
        page=DriveDeltaPage(items=[folder])
    )
    gateway.list_permissions.return_value = _fixture_permissions("visible_group")
    checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
    )

    output = list(
        connector._discover_from_checkpoint(
            0,
            0,
            checkpoint,
            include_permissions=True,
            add_group_prefix=False,
        )
    )

    node = next(
        item
        for item in output
        if isinstance(item, HierarchyNode)
        and item.raw_node_id == hierarchy_item_id("drive-1", folder.id)
    )
    assert node.external_access is not None
    assert node.external_access.external_user_group_ids == {
        build_ext_group_name_for_onyx("<visible-group-id>", DocumentSource.ONEDRIVE)
    }


def test_onedrive_fixture_child_before_parent_reads_child_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector, gateway = _connector()
    monkeypatch.setattr(
        "onyx.connectors.onedrive.connector.get_onedrive_external_access",
        map_onedrive_permissions,
    )
    destination = _fixture_item(
        "<folder-move-destination-id>", "incremental_delta_pages"
    )
    moved = _fixture_item("<file-move-id>", "incremental_delta_pages")
    gateway.list_permissions.return_value = _fixture_permissions(
        "move_destination_after"
    )
    gateway.download_item.return_value = DriveItemContent(
        sections=[TextSection(text="body")]
    )
    gateway.get_delta_page.return_value = OneDriveDeltaResult(
        page=DriveDeltaPage(items=[moved, destination])
    )
    checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
    )

    output, _ = _run_perm_step(connector, checkpoint)

    assert [item.id for item in output if isinstance(item, Document)] == [moved.id]
    assert [
        call.kwargs["item_id"] for call in gateway.list_permissions.call_args_list
    ] == [moved.id, destination.id]


def test_onedrive_fixture_cache_loss_checkpoint_restart_reads_item_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector, gateway = _connector()
    monkeypatch.setattr(
        "onyx.connectors.onedrive.connector.get_onedrive_external_access",
        map_onedrive_permissions,
    )
    destination = _fixture_item(
        "<folder-move-destination-id>", "incremental_delta_pages"
    )
    moved = _fixture_item("<file-move-id>", "incremental_delta_pages")
    gateway.list_permissions.return_value = _fixture_permissions(
        "move_destination_after"
    )
    gateway.download_item.return_value = DriveItemContent(
        sections=[TextSection(text="body")]
    )
    gateway.get_delta_page.side_effect = [
        OneDriveDeltaResult(
            page=DriveDeltaPage(items=[destination]),
            next_cursor="next-delta",
        ),
        OneDriveDeltaResult(page=DriveDeltaPage(items=[moved])),
    ]
    checkpoint = OneDriveCheckpoint(
        has_more=True,
        current_user=_user(),
        current_drive=_drive(),
    )

    _, checkpoint = _run_perm_step(connector, checkpoint)
    checkpoint = connector.validate_checkpoint_json(checkpoint.model_dump_json())
    connector._folder_access.clear()
    output, _ = _run_perm_step(connector, checkpoint)

    documents = [item for item in output if isinstance(item, Document)]
    assert len(documents) == 1
    access = documents[0].external_access
    assert access is not None
    assert "<alternate-user-email>" in access.external_user_emails
    assert [
        call.kwargs["item_id"] for call in gateway.list_permissions.call_args_list
    ] == [destination.id, moved.id]


def test_onedrive_slim_walk_is_complete_without_downloads() -> None:
    connector, gateway = _connector()
    gateway.list_users.return_value = OneDriveUserPage(users=[_user()])
    gateway.get_default_drive.return_value = _drive()
    gateway.get_delta_page.return_value = OneDriveDeltaResult(
        page=DriveDeltaPage(items=[_file_item()])
    )

    batches = list(connector.retrieve_all_slim_docs())

    assert len(batches) == 1
    assert isinstance(batches[0][0], HierarchyNode)
    slim_document = batches[0][1]
    assert isinstance(slim_document, SlimDocument)
    assert slim_document.id == "raw-item-id"
    gateway.download_item.assert_not_called()


def test_onedrive_slim_walk_fails_on_unselected_user_drive() -> None:
    connector, gateway = _connector()
    gateway.list_users.side_effect = [
        OneDriveUserPage(
            users=[_user("denied@example.com")],
            next_link="next-users",
        ),
        OneDriveUserPage(users=[_user("readable@example.com")]),
    ]
    gateway.get_default_drive.side_effect = [
        OneDriveGraphError(403, "accessDenied", "not selected"),
        _drive(),
    ]
    gateway.get_delta_page.return_value = OneDriveDeltaResult(page=DriveDeltaPage())

    with pytest.raises(RuntimeError, match="slim retrieval failed"):
        list(connector.retrieve_all_slim_docs())

    assert gateway.list_users.call_count == 1
    gateway.get_default_drive.assert_called_once()


def test_onedrive_slim_walk_skips_missing_configured_user() -> None:
    connector, gateway = _connector(
        users=["missing@example.com", "readable@example.com"]
    )
    gateway.get_user.side_effect = [None, _user("readable@example.com")]
    gateway.get_default_drive.return_value = _drive()
    gateway.get_delta_page.return_value = OneDriveDeltaResult(page=DriveDeltaPage())

    batches = list(connector.retrieve_all_slim_docs())

    assert len(batches) == 1
    assert isinstance(batches[0][0], HierarchyNode)
    assert batches[0][0].display_name == "readable@example.com"
    assert gateway.get_user.call_count == 2


def test_onedrive_slim_walk_skips_missing_configured_drive() -> None:
    connector, gateway = _connector(
        users=["missing-drive@example.com", "readable@example.com"]
    )
    gateway.get_user.side_effect = [
        _user("missing-drive@example.com"),
        _user("readable@example.com"),
    ]
    gateway.get_default_drive.side_effect = [None, _drive()]
    gateway.get_delta_page.return_value = OneDriveDeltaResult(page=DriveDeltaPage())

    batches = list(connector.retrieve_all_slim_docs())

    assert len(batches) == 1
    assert isinstance(batches[0][0], HierarchyNode)
    assert batches[0][0].display_name == "readable@example.com"
    assert gateway.get_default_drive.call_count == 2


def test_onedrive_slim_walk_fails_on_unselected_delta() -> None:
    connector, gateway = _connector()
    gateway.list_users.return_value = OneDriveUserPage(
        users=[_user("denied@example.com"), _user("readable@example.com")]
    )
    gateway.get_default_drive.return_value = _drive()
    gateway.get_delta_page.side_effect = [
        OneDriveGraphError(403, "accessDenied", "not selected"),
        OneDriveDeltaResult(page=DriveDeltaPage()),
    ]

    with pytest.raises(RuntimeError, match="slim retrieval failed"):
        list(connector.retrieve_all_slim_docs())

    gateway.get_delta_page.assert_called_once()


def test_onedrive_path_and_time_gates_run_before_download() -> None:
    connector, gateway = _connector()
    connector.settings = connector.settings.model_copy(
        update={"excluded_paths": ["Folder/*"]}
    )
    item = _file_item()

    assert not connector._item_allowed(item, None, None)
    assert item.last_modified_datetime is not None
    assert not connector._item_allowed(
        item,
        item.last_modified_datetime.replace(year=2027),
        None,
    )
    unsupported = item.model_copy(update={"name": "archive.unsupported"})
    assert not connector._item_allowed(unsupported, None, None)
    gateway.download_item.assert_not_called()


def test_onedrive_checks_and_registration_are_named() -> None:
    checks = build_onedrive_indexing_checks()
    assert {check.check_id for check in checks} == {
        "onedrive_token_auth",
        "onedrive_users",
        "onedrive_configured_users",
        "onedrive_drive",
        "onedrive_delta",
    }
    assert DocumentSource.ONEDRIVE in CONNECTOR_CLASS_MAP


def test_onedrive_named_capability_checks_pass_through_gateway() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.list_users.return_value = OneDriveUserPage(users=[_user()])
    gateway.get_user.return_value = _user()
    gateway.get_default_drive.return_value = _drive()
    gateway.get_delta_page.return_value = OneDriveDeltaResult(page=DriveDeltaPage())
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={"users": ["owner@example.com"]},
        source_operations=gateway,
    )

    for check in build_onedrive_indexing_checks():
        check.run(context)


def test_onedrive_capability_denial_is_actionable() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.list_users.side_effect = OneDriveGraphError(403, "accessDenied", "denied")
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={},
        source_operations=gateway,
    )
    check = next(
        check
        for check in build_onedrive_indexing_checks()
        if check.check_id == "onedrive_users"
    )

    with pytest.raises(InsufficientPermissionsError):
        check.run(context)


def test_onedrive_capability_user_probe_is_bounded_for_mock_pages() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={},
        source_operations=gateway,
    )
    check = next(
        check
        for check in build_onedrive_indexing_checks()
        if check.check_id == "onedrive_drive"
    )

    with pytest.raises(ConnectorValidationError, match="No readable OneDrive"):
        check.run(context)
    assert gateway.list_users.call_count == 20


def test_onedrive_capability_config_rejects_wrong_field_types() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={"users": "owner@example.com"},
        source_operations=gateway,
    )
    check = next(
        check
        for check in build_onedrive_indexing_checks()
        if check.check_id == "onedrive_configured_users"
    )

    with pytest.raises(ConnectorValidationError, match="configuration"):
        check.run(context)


def test_onedrive_drive_check_skips_unavailable_discovered_users() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.list_users.side_effect = [
        OneDriveUserPage(users=[_user("first@example.com")], next_link="next-users"),
        OneDriveUserPage(users=[_user("second@example.com")]),
    ]
    gateway.get_default_drive.side_effect = [
        OneDriveGraphError(423, "locked", "not selected"),
        _drive(),
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={},
        source_operations=gateway,
    )
    check = next(
        check
        for check in build_onedrive_indexing_checks()
        if check.check_id == "onedrive_drive"
    )

    check.run(context)

    assert gateway.get_default_drive.call_count == 2


def test_onedrive_drive_check_follows_all_user_pages() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.list_users.side_effect = [
        *[
            OneDriveUserPage(users=[], next_link=f"next-users-{page}")
            for page in range(19)
        ],
        OneDriveUserPage(users=[_user()]),
    ]
    gateway.get_default_drive.return_value = _drive()
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={},
        source_operations=gateway,
    )
    check = next(
        check
        for check in build_onedrive_indexing_checks()
        if check.check_id == "onedrive_drive"
    )

    check.run(context)

    assert gateway.list_users.call_count == 20
    assert gateway.list_users.call_args.kwargs["page_size"] == 1


def test_onedrive_drive_check_remembers_candidate_denial() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.list_users.side_effect = [
        OneDriveUserPage(
            users=[_user(f"user-{page}@example.com")],
            next_link=f"next-users-{page}",
        )
        for page in range(20)
    ]
    gateway.get_default_drive.side_effect = [
        OneDriveGraphError(403, "accessDenied", "not selected") for _ in range(20)
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={},
        source_operations=gateway,
    )
    check = next(
        check
        for check in build_onedrive_indexing_checks()
        if check.check_id == "onedrive_drive"
    )

    with pytest.raises(InsufficientPermissionsError):
        check.run(context)

    assert gateway.list_users.call_count == 20
    assert gateway.get_default_drive.call_count == 20


def test_onedrive_delta_check_finds_later_readable_configured_drive() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.get_user.side_effect = [
        _user("first@example.com"),
        _user("second@example.com"),
    ]
    gateway.get_default_drive.side_effect = [
        OneDriveDrive(id="first-drive", name="First"),
        OneDriveDrive(id="second-drive", name="Second"),
    ]
    gateway.get_delta_page.side_effect = [
        OneDriveGraphError(403, "accessDenied", "not selected"),
        OneDriveDeltaResult(page=DriveDeltaPage()),
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={
            "users": ["first@example.com", "second@example.com"]
        },
        source_operations=gateway,
    )
    check = next(
        check
        for check in build_onedrive_indexing_checks()
        if check.check_id == "onedrive_delta"
    )

    check.run(context)

    assert gateway.get_delta_page.call_count == 2
    assert gateway.get_delta_page.call_args.kwargs["drive_id"] == "second-drive"


def test_onedrive_permission_and_group_checks_use_gateway() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.get_user.return_value = _user()
    gateway.get_default_drive.return_value = _drive()
    gateway.get_delta_page.return_value = OneDriveDeltaResult(
        page=DriveDeltaPage(items=[_file_item()])
    )
    gateway.list_permissions.return_value = OneDrivePermissionPage(permissions=[])
    gateway.list_groups.return_value = OneDriveGroupPage(
        groups=[OneDriveGroup(id="group", displayName="Visible")]
    )
    gateway.list_transitive_group_members.return_value = OneDriveGroupMemberPage(
        members=[]
    )
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={"users": ["owner@example.com"]},
        source_operations=gateway,
    )

    checks = (
        build_onedrive_doc_permission_sync_checks() + build_onedrive_group_sync_checks()
    )
    for check in checks:
        check.run(context)

    gateway.list_permissions.assert_called_once_with(
        drive_id="drive-1", item_id="raw-item-id"
    )
    gateway.list_transitive_group_members.assert_called_once_with(group_id="group")


def test_onedrive_permission_check_follows_tombstone_pages() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.get_user.return_value = _user()
    gateway.get_default_drive.return_value = _drive()
    tombstone = DriveDeltaItem.model_validate(
        {"id": "deleted", "deleted": {"state": "deleted"}}
    )
    gateway.get_delta_page.side_effect = [
        OneDriveDeltaResult(
            page=DriveDeltaPage(items=[tombstone]),
            next_cursor="next-delta",
        ),
        OneDriveDeltaResult(page=DriveDeltaPage(items=[_file_item()])),
    ]
    gateway.list_permissions.return_value = OneDrivePermissionPage(permissions=[])
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={"users": ["owner@example.com"]},
        source_operations=gateway,
    )

    build_onedrive_doc_permission_sync_checks()[0].run(context)

    assert gateway.get_delta_page.call_count == 2
    assert gateway.get_delta_page.call_args.kwargs["page_url"] == "next-delta"
    gateway.list_permissions.assert_called_once_with(
        drive_id="drive-1", item_id="raw-item-id"
    )


def test_onedrive_permission_check_accepts_empty_drive_at_end_cursor() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.get_user.return_value = _user()
    gateway.get_default_drive.return_value = _drive()
    gateway.get_delta_page.return_value = OneDriveDeltaResult(page=DriveDeltaPage())
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={"users": ["owner@example.com"]},
        source_operations=gateway,
    )

    build_onedrive_doc_permission_sync_checks()[0].run(context)

    gateway.get_delta_page.assert_called_once()
    gateway.list_permissions.assert_not_called()


def test_onedrive_permission_check_probes_past_empty_drive() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.get_user.side_effect = [
        _user("empty@example.com"),
        _user("populated@example.com"),
    ]
    gateway.get_default_drive.side_effect = [
        OneDriveDrive(id="empty-drive", name="Empty"),
        OneDriveDrive(id="populated-drive", name="Populated"),
    ]
    gateway.get_delta_page.side_effect = [
        OneDriveDeltaResult(page=DriveDeltaPage()),
        OneDriveDeltaResult(page=DriveDeltaPage(items=[_file_item()])),
    ]
    gateway.list_permissions.return_value = OneDrivePermissionPage(permissions=[])
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={
            "users": ["empty@example.com", "populated@example.com"]
        },
        source_operations=gateway,
    )

    build_onedrive_doc_permission_sync_checks()[0].run(context)

    assert gateway.get_delta_page.call_count == 2
    gateway.list_permissions.assert_called_once_with(
        drive_id="populated-drive", item_id="raw-item-id"
    )


def test_onedrive_permission_check_bounds_empty_delta_pages() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.get_user.return_value = _user()
    gateway.get_default_drive.return_value = _drive()
    gateway.get_delta_page.return_value = OneDriveDeltaResult(
        page=DriveDeltaPage(),
        next_cursor="another-empty-page",
    )
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        connector_specific_config={"users": ["owner@example.com"]},
        source_operations=gateway,
    )

    with pytest.raises(
        ConnectorValidationError, match="No readable OneDrive item was found"
    ):
        build_onedrive_doc_permission_sync_checks()[0].run(context)

    assert gateway.get_delta_page.call_count == 20
    gateway.list_permissions.assert_not_called()


def test_onedrive_hidden_group_check_does_not_require_optional_scope() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.list_groups.return_value = OneDriveGroupPage(
        groups=[
            OneDriveGroup(
                id="hidden", displayName="Hidden", visibility="HiddenMembership"
            )
        ]
    )
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        source_operations=gateway,
    )
    check = next(
        check
        for check in build_onedrive_group_sync_checks()
        if check.check_id == "onedrive_group_members"
    )

    check.run(context)

    gateway.list_transitive_group_members.assert_not_called()


def test_onedrive_group_check_skips_hidden_group_for_later_visible_group() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.list_groups.side_effect = [
        OneDriveGroupPage(
            groups=[
                OneDriveGroup(
                    id="hidden",
                    displayName="Hidden",
                    visibility="HiddenMembership",
                )
            ],
            next_link="next-groups",
        ),
        OneDriveGroupPage(groups=[OneDriveGroup(id="visible", displayName="Visible")]),
    ]
    gateway.list_transitive_group_members.return_value = OneDriveGroupMemberPage(
        members=[]
    )
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        source_operations=gateway,
    )
    check = next(
        check
        for check in build_onedrive_group_sync_checks()
        if check.check_id == "onedrive_group_members"
    )

    check.run(context)

    assert gateway.list_groups.call_count == 2
    gateway.list_transitive_group_members.assert_called_once_with(group_id="visible")


def test_onedrive_group_check_uses_first_visible_group() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.list_groups.side_effect = [
        OneDriveGroupPage(
            groups=[OneDriveGroup(id="visible", displayName="Visible")],
            next_link="next-groups",
        ),
        OneDriveGroupPage(groups=[]),
    ]
    gateway.list_transitive_group_members.return_value = OneDriveGroupMemberPage(
        members=[]
    )
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        source_operations=gateway,
    )
    check = next(
        check
        for check in build_onedrive_group_sync_checks()
        if check.check_id == "onedrive_group_members"
    )

    check.run(context)

    assert gateway.list_groups.call_count == 1
    gateway.list_transitive_group_members.assert_called_once_with(group_id="visible")


def test_onedrive_group_check_bounds_hidden_group_discovery() -> None:
    gateway: Any = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.list_groups.return_value = OneDriveGroupPage(
        groups=[
            OneDriveGroup(
                id="hidden",
                displayName="Hidden",
                visibility="HiddenMembership",
            )
        ],
        next_link="another-group-page",
    )
    gateway.list_transitive_group_members.return_value = OneDriveGroupMemberPage(
        members=[]
    )
    context = CapabilityCheckContext(
        source=DocumentSource.ONEDRIVE,
        credential_json={},
        source_operations=gateway,
    )
    check = next(
        check
        for check in build_onedrive_group_sync_checks()
        if check.check_id == "onedrive_group_members"
    )

    check.run(context)

    assert gateway.list_groups.call_count == 20
    gateway.list_transitive_group_members.assert_not_called()


def test_onedrive_hybrid_permissions_inherit_known_parent_and_read_shared_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector, gateway = _connector()
    inherited_access = ExternalAccess(
        external_user_emails={"parent@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )
    direct_access = ExternalAccess(
        external_user_emails={"child@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )
    gateway.list_permissions.return_value = OneDrivePermissionPage(permissions=[])
    mapper = MagicMock()
    mapper.side_effect = [inherited_access, direct_access]
    monkeypatch.setattr(
        "onyx.connectors.onedrive.connector.get_onedrive_external_access", mapper
    )
    user = _user()
    drive = _drive()
    folder = _folder_item()
    child = _file_item()
    shared_child = child.model_copy(
        update={
            "id": "shared-child",
            "shared": {"scope": "users"},
        }
    )

    assert connector._item_access(user, drive, folder, add_prefix=False) == (
        inherited_access
    )
    assert connector._item_access(user, drive, child, add_prefix=False) == (
        inherited_access
    )
    assert connector._item_access(user, drive, shared_child, add_prefix=False) == (
        direct_access
    )
    assert gateway.list_permissions.call_count == 2
