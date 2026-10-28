"""Azure RBAC readers of a container: roles whose data actions read blobs,
minus deny assignments. Conditioned assignments and principals that are not
users or groups are left out."""

import pytest

from ee.onyx.external_permissions.azure_datalake.directory import GraphDirectory
from ee.onyx.external_permissions.azure_datalake.principals import (
    everyone_term,
    group_term,
    user_term,
)
from ee.onyx.external_permissions.azure_datalake.rbac import (
    RbacReaders,
    find_storage_account,
    rbac_readers,
    role_reads_blobs,
)
from onyx.connectors.azure_datalake.models import (
    AzureDenyAssignment,
    AzurePrincipal,
    AzureRoleAssignment,
    AzureRolePermission,
    AzureStorageAccountPage,
)
from onyx.connectors.exceptions import ConnectorValidationError
from tests.unit.ee.onyx.external_permissions.azure_datalake.azure_datalake_fakes import (
    ACCOUNT,
    ACCOUNT_ID,
    ADMIN,
    APP,
    DATA_OWNER_ROLE,
    DATA_READER_ROLE,
    GROUP_B,
    OWNER,
    RAUNAK,
    RBAC_GROUP,
    READER_ROLE,
    SCOPE,
    assignment,
    fake_ops,
    role,
)


@pytest.mark.parametrize(
    ("data_actions", "not_data_actions", "reads"),
    [
        (
            ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"],
            [],
            True,
        ),
        (["*"], [], True),
        (["microsoft.storage/*"], [], True),
        (
            ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/*"],
            [],
            True,
        ),
        (
            ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/*"],
            ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"],
            False,
        ),
        (
            ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write"],
            [],
            False,
        ),
        ([], [], False),
    ],
)
def test_role_reads_blobs(
    data_actions: list[str], not_data_actions: list[str], reads: bool
) -> None:
    assert role_reads_blobs(role("r", data_actions, not_data_actions)) is reads


def _readers(
    assignments: list[AzureRoleAssignment] | None = None,
    denies: list[AzureDenyAssignment] | None = None,
) -> RbacReaders:
    ops = fake_ops({}, assignments=assignments, denies=denies)
    return rbac_readers(ops, SCOPE, GraphDirectory(ops))


def test_readers_skip_service_principals_and_control_plane_roles() -> None:
    readers = _readers()

    assert readers.principals == frozenset({user_term(OWNER), group_term(RBAC_GROUP)})
    assert readers.skipped_principal_ids == [APP]


def test_conditioned_assignments_are_reported_not_granted() -> None:
    readers = _readers(
        assignments=[
            assignment(RAUNAK, "User", DATA_READER_ROLE, condition="@Resource[...]"),
            assignment(ADMIN, "User", READER_ROLE, condition="@Resource[...]"),
        ]
    )

    assert readers.principals == frozenset()
    assert readers.conditioned_assignment_ids == [f"{RAUNAK}-{DATA_READER_ROLE}"]


def _deny(
    principals: list[AzurePrincipal],
    excluded: list[AzurePrincipal] | None = None,
    scope: str = SCOPE,
    child_scopes: bool = True,
) -> AzureDenyAssignment:
    return AzureDenyAssignment(
        id="deny",
        scope=scope,
        permissions=[AzureRolePermission(data_actions=["*"])],
        principals=principals,
        exclude_principals=excluded or [],
        do_not_apply_to_child_scopes=not child_scopes,
    )


def test_deny_removes_a_user_and_a_group() -> None:
    readers = _readers(
        assignments=[
            assignment(RAUNAK, "User", DATA_OWNER_ROLE),
            assignment(ADMIN, "User", DATA_OWNER_ROLE),
            assignment(RBAC_GROUP, "Group", DATA_READER_ROLE),
        ],
        denies=[
            _deny(
                [
                    AzurePrincipal(id=RBAC_GROUP, type="Group"),
                    AzurePrincipal(id=GROUP_B, type="Group"),
                ]
            )
        ],
    )

    # Raunak and the admin are in group B.
    assert readers.principals == frozenset()


def test_deny_for_everyone_keeps_only_excluded_principals() -> None:
    readers = _readers(
        denies=[
            _deny(
                [
                    AzurePrincipal(
                        id="00000000-0000-0000-0000-000000000000", type="SystemDefined"
                    )
                ],
                excluded=[AzurePrincipal(id=OWNER, type="User")],
            )
        ]
    )

    assert readers.principals == frozenset({user_term(OWNER)})


def test_deny_on_a_parent_scope_that_skips_children_does_not_apply() -> None:
    readers = _readers(
        denies=[
            _deny(
                [AzurePrincipal(id=OWNER, type="User")],
                scope=ACCOUNT_ID,
                child_scopes=False,
            )
        ]
    )

    assert user_term(OWNER) in readers.principals


def test_deny_for_a_group_narrows_an_everyone_free_group_term() -> None:
    readers = _readers(
        assignments=[assignment(GROUP_B, "Group", DATA_READER_ROLE)],
        denies=[_deny([AzurePrincipal(id=RAUNAK, type="User")])],
    )

    assert readers.principals == frozenset(
        {group_term(GROUP_B, excluded_users={RAUNAK})}
    )
    assert everyone_term() not in readers.principals


def test_find_storage_account_by_name() -> None:
    ops = fake_ops({})

    assert find_storage_account(ops, ACCOUNT.upper()).id == ACCOUNT_ID


def test_storage_account_not_visible() -> None:
    ops = fake_ops({})
    ops.list_storage_accounts.return_value = AzureStorageAccountPage(accounts=[])

    with pytest.raises(ConnectorValidationError, match="Reader role"):
        find_storage_account(ops, ACCOUNT)
