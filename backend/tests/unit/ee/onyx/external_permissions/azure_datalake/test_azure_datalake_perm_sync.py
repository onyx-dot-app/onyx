"""Azure Data Lake permission sync: the slim walk, the group sync, and the
named checks."""

from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.external_permissions.azure_datalake.capability_checks import (
    build_azure_datalake_doc_permission_sync_checks,
    build_azure_datalake_group_sync_checks,
)
from ee.onyx.external_permissions.azure_datalake.connector import (
    azure_datalake_connector,
)
from ee.onyx.external_permissions.azure_datalake.group_sync import tenant_groups
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.azure_datalake.connector import AzureDataLakeConnector
from onyx.connectors.azure_datalake.models import AzureDataLakePathPage
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckOutput,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
)
from onyx.connectors.microsoft_utils.entra import (
    EntraDirectoryObject,
    EntraPage,
    EntraUser,
)
from onyx.connectors.models import HierarchyNode, SlimDocument
from tests.unit.ee.onyx.external_permissions.azure_datalake.azure_datalake_fakes import (
    ACCOUNT,
    CONTAINER,
    DATA_READER_ROLE,
    GROUP_A,
    GROUP_B,
    RAUNAK,
    RBAC_GROUP,
    TENANT,
    access,
    assignment,
    directory,
    fake_ops,
    file,
)

EVERYONE_GROUP = f"entra_tenant_everyone:{TENANT}"
ACLS = {
    "": access("user::rwx,group::---,other::--x"),
    "docs": access(f"user::rwx,group::---,group:{GROUP_A}:r-x,mask::r-x,other::---"),
    "docs/readme.txt": access(
        f"user::rw-,group::---,group:{GROUP_A}:r--,mask::r--,other::---"
    ),
    "docs/image.xyz": access("user::rw-,group::---,other::r--"),
}


@pytest.mark.usefixtures("enable_ee")
def test_slim_walk_names_bare_groups_on_files_and_prefixed_groups_on_nodes() -> None:
    ops = fake_ops(ACLS)
    ops.list_paths_page.return_value = AzureDataLakePathPage(
        paths=[
            directory("docs"),
            file("docs/readme.txt"),
            file("docs/image.xyz"),
        ],
        continuation_token=None,
    )
    connector = AzureDataLakeConnector(account_name=ACCOUNT, container_name=CONTAINER)
    connector._ops = ops

    batches = list(connector.retrieve_all_slim_docs_perm_sync())

    items = [item for batch in batches for item in batch]
    documents = [item for item in items if isinstance(item, SlimDocument)]
    nodes = {
        item.raw_node_id: item for item in items if isinstance(item, HierarchyNode)
    }
    # The unsupported extension is not indexed, so it is not listed.
    assert [document.id for document in documents] == [
        f"azure_datalake:{ACCOUNT}:{CONTAINER}:docs/readme.txt"
    ]
    document_access: ExternalAccess | None = documents[0].external_access
    assert document_access is not None
    assert document_access.external_user_group_ids == {GROUP_A, RBAC_GROUP}
    node_access = nodes[f"azure_datalake:{ACCOUNT}:{CONTAINER}:docs"].external_access
    assert node_access is not None
    assert node_access.external_user_group_ids == {
        build_ext_group_name_for_onyx(GROUP_A, DocumentSource.AZURE_DATALAKE),
        build_ext_group_name_for_onyx(RBAC_GROUP, DocumentSource.AZURE_DATALAKE),
    }
    container_access = nodes[f"azure_datalake:{ACCOUNT}:{CONTAINER}"].external_access
    assert container_access is not None


@pytest.mark.usefixtures("enable_ee")
def test_slim_walk_stops_on_signal() -> None:
    ops = fake_ops(ACLS)
    connector = AzureDataLakeConnector(account_name=ACCOUNT, container_name=CONTAINER)
    connector._ops = ops
    callback = MagicMock()
    callback.should_stop.return_value = True

    with pytest.raises(RuntimeError, match="stop signal"):
        list(connector.retrieve_all_slim_docs_perm_sync(callback=callback))


SYNC_CONNECTOR_MODULE = "ee.onyx.external_permissions.azure_datalake.connector"


def test_group_sync_yields_the_tenant_and_every_group() -> None:
    groups = {group.id: group for group in tenant_groups(fake_ops({}), set())}

    assert set(groups) == {EVERYONE_GROUP, GROUP_A, GROUP_B, RBAC_GROUP}
    assert groups[EVERYONE_GROUP].user_emails == sorted(
        [
            "owner@onyx.app",
            "raunak@onyx.app",
            "subash@onyx.app",
            "admin@onyx.app",
            "guest@example.com",
        ]
    )
    assert groups[GROUP_B].user_emails == ["admin@onyx.app", "raunak@onyx.app"]


def _context(ops: MagicMock, credential_json: dict[str, str]) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.AZURE_DATALAKE,
        credential_json=credential_json,
        connector_specific_config={
            "account_name": ACCOUNT,
            "container_name": CONTAINER,
        },
        source_operations=ops,
    )


def _checks() -> dict[str, CapabilityCheck]:
    return {
        check.check_id: check
        for check in build_azure_datalake_doc_permission_sync_checks()
        + build_azure_datalake_group_sync_checks()
    }


def test_every_check_passes_for_the_test_app() -> None:
    ops = fake_ops(ACLS)
    ops.list_paths_page.return_value = AzureDataLakePathPage(
        paths=[file("docs/readme.txt")], continuation_token=None
    )
    context = _context(ops, {"authentication_method": "certificate"})

    for check in _checks().values():
        check.run(context)


def test_account_key_fails_the_app_registration_check() -> None:
    check = _checks()["adls_perm_sync_app_registration"]

    with pytest.raises(ConnectorValidationError, match="app registration"):
        check.run(_context(fake_ops({}), {"authentication_method": "account_key"}))


def test_conditioned_role_assignment_is_an_advisory() -> None:
    ops = fake_ops(
        {},
        assignments=[
            assignment(RAUNAK, "User", DATA_READER_ROLE, condition="@Resource[...]")
        ],
    )

    output = _checks()["adls_role_assignments"].run(
        _context(ops, {"authentication_method": "client_secret"})
    )

    assert isinstance(output, CheckOutput)
    assert len(output.advisories) == 1


def test_a_sample_of_disabled_users_does_not_fail_the_users_check() -> None:
    ops = fake_ops({})
    ops.list_users.return_value = EntraPage[EntraUser](
        items=[
            EntraUser.model_validate(
                {
                    "id": RAUNAK,
                    "userPrincipalName": "raunak@onyx.app",
                    "accountEnabled": False,
                }
            )
        ]
    )

    _checks()["adls_graph_users"].run(
        _context(ops, {"authentication_method": "client_secret"})
    )


def test_the_sync_connector_admits_images_like_indexing() -> None:
    cc_pair = MagicMock()
    cc_pair.connector.source = DocumentSource.AZURE_DATALAKE
    cc_pair.connector.connector_specific_config = {
        "account_name": ACCOUNT,
        "container_name": CONTAINER,
    }
    with (
        patch(
            f"{SYNC_CONNECTOR_MODULE}.get_image_extraction_and_analysis_enabled",
            return_value=True,
        ),
        patch(f"{SYNC_CONNECTOR_MODULE}.build_db_credentials_provider"),
    ):
        connector = azure_datalake_connector(cc_pair)

    assert connector._is_indexable(file("images/square.png"))


def _refusing_group(refused: set[str]) -> MagicMock:
    ops = fake_ops({})
    read_members = ops.list_transitive_group_members.side_effect

    def members(
        *, group_id: str, next_link: str | None = None
    ) -> EntraPage[EntraDirectoryObject]:
        if group_id in refused:
            raise InsufficientPermissionsError("hidden membership")
        return read_members(group_id=group_id, next_link=next_link)

    ops.list_transitive_group_members.side_effect = members
    return ops


def test_one_group_with_hidden_members_does_not_fail_the_members_check() -> None:
    first_group = fake_ops({}).list_groups().items[0].id
    ops = _refusing_group({first_group})

    _checks()["adls_graph_group_members"].run(
        _context(ops, {"authentication_method": "client_secret"})
    )


def test_a_refusal_for_every_group_fails_the_members_check() -> None:
    groups = {group.id for group in fake_ops({}).list_groups().items}
    ops = _refusing_group(groups)

    with pytest.raises(InsufficientPermissionsError):
        _checks()["adls_graph_group_members"].run(
            _context(ops, {"authentication_method": "client_secret"})
        )
