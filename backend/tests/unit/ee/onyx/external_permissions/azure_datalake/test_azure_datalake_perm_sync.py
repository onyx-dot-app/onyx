"""Azure Data Lake permission sync: the slim walk, the group sync, and the
named checks."""

from unittest.mock import MagicMock

import pytest

from ee.onyx.external_permissions.azure_datalake.capability_checks import (
    build_azure_datalake_doc_permission_sync_checks,
    build_azure_datalake_group_sync_checks,
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
from onyx.connectors.exceptions import ConnectorValidationError
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


def test_group_sync_yields_the_tenant_and_every_group() -> None:
    groups = {group.id: group for group in tenant_groups(fake_ops({}))}

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
