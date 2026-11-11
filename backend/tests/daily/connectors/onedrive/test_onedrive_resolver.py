"""Live tests for OneDriveConnector.reindex against the fixed tenant corpus."""

from collections.abc import Iterable

import pytest

from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
)
from onyx.connectors.onedrive.connector import (
    OneDriveConnector,
    drive_root_id,
    hierarchy_item_id,
)
from tests.utils.onedrive_fixture import (
    FilePath,
    FixtureState,
    FolderPath,
    GraphItem,
    build_fixture_reader,
    load_fixture_config,
)
from tests.utils.pytest_secrets import RedactedDict
from tests.utils.secret_names import TestSecret

pytestmark = [
    pytest.mark.usefixtures("enable_ee", "mock_get_unstructured_api_key"),
    pytest.mark.secrets(
        TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID,
        TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID,
        TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY,
        TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD,
    ),
]

# Well-formed OneDrive item id that no drive contains.
BOGUS_ITEM_ID = "01VDPSAMAAAAAAAAAAAAAAAAAAAAAAAAAA"
UNPARSEABLE_ITEM_ID = "not a drive item/../id?"


@pytest.fixture(scope="module")
def state() -> FixtureState:
    return build_fixture_reader(load_fixture_config()).load_state()


@pytest.fixture(scope="module")
def credentials(test_secrets: dict[TestSecret, str]) -> RedactedDict[str, str]:
    return RedactedDict(
        {
            "authentication_method": MicrosoftAuthMethod.CERTIFICATE.value,
            "onedrive_client_id": test_secrets[
                TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID
            ],
            "onedrive_directory_id": test_secrets[
                TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID
            ],
            "onedrive_private_key": test_secrets[
                TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY
            ],
            "onedrive_certificate_password": test_secrets[
                TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD
            ],
        }
    )


def _connector(
    state: FixtureState,
    credentials: dict[str, str],
    users: list[str] | None = None,
) -> OneDriveConnector:
    connector = OneDriveConnector(
        users=(
            users
            if users is not None
            else [
                state.owner.user_principal_name,
                state.second_owner.user_principal_name,
            ]
        ),
        excluded_paths=state.excluded_paths,
        treat_organization_link_as_public=True,
    )
    connector.load_credentials(credentials)
    return connector


def _failure(document_id: str, link: str | None) -> ConnectorFailure:
    return ConnectorFailure(
        failed_document=DocumentFailure(document_id=document_id, document_link=link),
        failure_message=f"Synthetic failure for {document_id}",
    )


def _failures(items: Iterable[GraphItem], *, with_link: bool) -> list[ConnectorFailure]:
    return [_failure(item.id, item.web_url if with_link else None) for item in items]


def _run(
    connector: OneDriveConnector,
    errors: list[ConnectorFailure],
    *,
    include_permissions: bool = False,
) -> tuple[list[Document], list[ConnectorFailure], list[HierarchyNode]]:
    results = list(connector.reindex(errors, include_permissions=include_permissions))
    return (
        [r for r in results if isinstance(r, Document)],
        [r for r in results if isinstance(r, ConnectorFailure)],
        [r for r in results if isinstance(r, HierarchyNode)],
    )


def _failed_ids(failures: list[ConnectorFailure]) -> set[str]:
    return {f.failed_document.document_id for f in failures if f.failed_document}


def _folder_node_id(state: FixtureState, folder: FolderPath) -> str:
    return hierarchy_item_id(state.drive.id, state.folders[folder].id)


def test_reindex_single_file_with_link(
    state: FixtureState, credentials: dict[str, str]
) -> None:
    target = state.files[FilePath.INHERITED_NESTED]

    docs, failures, nodes = _run(
        _connector(state, credentials), _failures([target], with_link=True)
    )

    assert failures == []
    assert [doc.id for doc in docs] == [target.id]
    assert docs[0].parent_hierarchy_raw_node_id == _folder_node_id(
        state, FolderPath.INHERITED_NESTED
    )
    # Root -> fixture root -> 20-inherited -> nested, parents before children.
    nodes_by_id = {node.raw_node_id: node for node in nodes}
    root_id = drive_root_id(state.drive.id)
    fixture_root_id = hierarchy_item_id(state.drive.id, state.root_item.id)
    inherited_id = _folder_node_id(state, FolderPath.INHERITED)
    nested_id = _folder_node_id(state, FolderPath.INHERITED_NESTED)
    assert [node.raw_node_id for node in nodes] == [
        root_id,
        fixture_root_id,
        inherited_id,
        nested_id,
    ]
    assert nodes_by_id[fixture_root_id].raw_parent_id == root_id
    assert nodes_by_id[inherited_id].raw_parent_id == fixture_root_id
    assert nodes_by_id[nested_id].raw_parent_id == inherited_id


def test_reindex_multiple_files_across_drives(
    state: FixtureState, credentials: dict[str, str]
) -> None:
    targets = [
        state.files[FilePath.PRIVATE],
        state.files[FilePath.DIRECT],
        state.files[FilePath.INHERITED],
        state.files[FilePath.INHERITED_NESTED],
        state.files[FilePath.IDENTITY],
        state.second_drive_duplicate,
    ]

    docs, failures, nodes = _run(
        _connector(state, credentials), _failures(targets, with_link=True)
    )

    assert failures == []
    assert sorted(doc.id for doc in docs) == sorted(item.id for item in targets)
    node_ids = [node.raw_node_id for node in nodes]
    # Shared ancestors are emitted once per call.
    assert len(node_ids) == len(set(node_ids))
    assert drive_root_id(state.drive.id) in node_ids
    assert drive_root_id(state.second_drive.id) in node_ids


def test_reindex_without_link_probes_configured_drives(
    state: FixtureState, credentials: dict[str, str]
) -> None:
    targets = [state.files[FilePath.DIRECT], state.second_drive_duplicate]

    docs, failures, _ = _run(
        _connector(state, credentials), _failures(targets, with_link=False)
    )

    assert failures == []
    assert sorted(doc.id for doc in docs) == sorted(item.id for item in targets)


def test_reindex_all_users_mode(
    state: FixtureState, credentials: dict[str, str]
) -> None:
    linked = state.files[FilePath.PRIVATE]
    unlinked = state.files[FilePath.DIRECT]
    connector = _connector(state, credentials, users=[])

    docs, failures, _ = _run(
        connector,
        [_failure(linked.id, linked.web_url), _failure(unlinked.id, None)],
    )

    assert [doc.id for doc in docs] == [linked.id]
    assert _failed_ids(failures) == {unlinked.id}


def test_reindex_with_permissions(
    state: FixtureState, credentials: dict[str, str]
) -> None:
    owner = state.owner.user_principal_name.lower()
    primary = state.primary_user.user_principal_name.lower()
    expected = {
        FilePath.PRIVATE: ExternalAccess(
            external_user_emails={owner},
            external_user_group_ids=set(),
            is_public=False,
        ),
        FilePath.DIRECT: ExternalAccess(
            external_user_emails={owner, primary},
            external_user_group_ids=set(),
            is_public=False,
        ),
        FilePath.INHERITED_NESTED: ExternalAccess(
            external_user_emails={owner, primary},
            external_user_group_ids=set(),
            is_public=False,
        ),
        FilePath.ORGANIZATION_LINK: ExternalAccess(
            external_user_emails={owner},
            external_user_group_ids=set(),
            is_public=True,
        ),
    }
    group_target = state.files[FilePath.VISIBLE_GROUP]
    targets = [state.files[path] for path in expected] + [group_target]

    docs, failures, nodes = _run(
        _connector(state, credentials),
        _failures(targets, with_link=True),
        include_permissions=True,
    )

    assert failures == []
    docs_by_id = {doc.id: doc for doc in docs}
    for path, access in expected.items():
        assert docs_by_id[state.files[path].id].external_access == access
    group_access = docs_by_id[group_target.id].external_access
    assert group_access is not None
    assert group_access.external_user_group_ids == {
        build_ext_group_name_for_onyx(state.visible_group.id, DocumentSource.ONEDRIVE)
    }
    nodes_by_id = {node.raw_node_id: node for node in nodes}
    assert (
        nodes_by_id[drive_root_id(state.drive.id)].external_access
        == expected[FilePath.PRIVATE]
    )
    assert (
        nodes_by_id[_folder_node_id(state, FolderPath.INHERITED)].external_access
        == expected[FilePath.INHERITED_NESTED]
    )


def test_reindex_bogus_id_yields_failure(
    state: FixtureState, credentials: dict[str, str]
) -> None:
    link = state.files[FilePath.PRIVATE].web_url

    docs, failures, _ = _run(
        _connector(state, credentials),
        [_failure(BOGUS_ITEM_ID, link), _failure(BOGUS_ITEM_ID + "B", None)],
    )

    assert docs == []
    assert _failed_ids(failures) == {BOGUS_ITEM_ID, BOGUS_ITEM_ID + "B"}


def test_reindex_unparseable_id_yields_failure(
    state: FixtureState, credentials: dict[str, str]
) -> None:
    good = state.files[FilePath.DIRECT]

    docs, failures, _ = _run(
        _connector(state, credentials),
        [
            _failure(UNPARSEABLE_ITEM_ID, None),
            _failure("weird-link-id", "https://example.com/not/onedrive"),
            _failure(good.id, good.web_url),
        ],
    )

    # The bad targets do not stop the good one.
    assert [doc.id for doc in docs] == [good.id]
    assert _failed_ids(failures) == {UNPARSEABLE_ITEM_ID, "weird-link-id"}


def test_reindex_out_of_scope_yields_failure(
    state: FixtureState, credentials: dict[str, str]
) -> None:
    other_drive_item = state.second_drive_duplicate
    excluded = state.files[FilePath.UNSUPPORTED]
    folder = state.folders[FolderPath.DIRECT]
    connector = _connector(state, credentials, users=[state.owner.user_principal_name])

    docs, failures, _ = _run(
        connector,
        _failures([other_drive_item, excluded, folder], with_link=True)
        + [_failure(other_drive_item.id, None)],
    )

    assert docs == []
    assert len(failures) == 4
    assert _failed_ids(failures) == {other_drive_item.id, excluded.id, folder.id}


def test_reindex_empty_errors(state: FixtureState, credentials: dict[str, str]) -> None:
    assert list(_connector(state, credentials).reindex([])) == []


def test_reindex_entity_failures_are_skipped(
    state: FixtureState, credentials: dict[str, str]
) -> None:
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id=f"drive:{state.owner.id}"),
        failure_message="drive failure",
    )

    assert list(_connector(state, credentials).reindex([entity])) == []
