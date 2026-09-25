import json
from pathlib import Path
from typing import Any
from unittest.mock import create_autospec

import pytest

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
from onyx.connectors.onedrive.capability_checks import build_onedrive_indexing_checks
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
