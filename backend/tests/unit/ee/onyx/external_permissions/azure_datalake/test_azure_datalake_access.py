"""Azure Data Lake access: a file's readers are its RBAC readers plus those
its ACLs let read it and traverse every directory above it. The cases mirror
the adls-perm-fixture matrix of the live test container."""

import pytest

from ee.onyx.external_permissions.azure_datalake.access import (
    AzureDataLakeAccessResolver,
)
from ee.onyx.external_permissions.azure_datalake.acl import AclBit, granted_principals
from ee.onyx.external_permissions.azure_datalake.principals import (
    EVERYONE_TERM,
    PrincipalSet,
    everyone_term,
    group_term,
    user_term,
)
from onyx.access.models import ExternalAccess
from onyx.connectors.azure_datalake.models import AzureDataLakeAccessControl
from onyx.connectors.exceptions import InsufficientPermissionsError
from tests.unit.ee.onyx.external_permissions.azure_datalake.azure_datalake_fakes import (
    ACCOUNT,
    ADMIN,
    CONTAINER,
    GROUP_A,
    GROUP_B,
    OWNER,
    RAUNAK,
    RBAC_GROUP,
    TENANT,
    access,
    directory,
    fake_ops,
    file,
)

EVERYONE_GROUP = f"entra_tenant_everyone:{TENANT}"
ROOT_ACL = access("user::rwx,group::---,other::--x")
PRIVATE_FILE = "user::rw-,group::r--,other::---"
# Every file: the owner reads it, and so does the RBAC group.
BASE_EMAILS = {"owner@onyx.app"}
BASE_GROUPS = {RBAC_GROUP}


def _matrix() -> dict[str, AzureDataLakeAccessControl]:
    return {
        "": ROOT_ACL,
        "00-private": access("user::rwx,group::r-x,other::---"),
        "00-private/private.txt": access(PRIVATE_FILE),
        "10-named-user": access(
            f"user::rwx,user:{RAUNAK}:--x,group::---,mask::--x,other::---"
        ),
        "10-named-user/named-user.txt": access(
            f"user::rw-,user:{RAUNAK}:r--,group::---,mask::r--,other::---"
        ),
        "20-group-a": access(
            f"user::rwx,group::---,group:{GROUP_A}:--x,mask::--x,other::---"
        ),
        "20-group-a/group-a.txt": access(
            f"user::rw-,group::---,group:{GROUP_A}:r--,mask::r--,other::---"
        ),
        "30-cross-group": access(
            f"user::rwx,group::---,group:{GROUP_A}:--x,mask::--x,other::---"
        ),
        "30-cross-group/cross-group.txt": access(
            f"user::rw-,group::---,group:{GROUP_B}:r--,mask::r--,other::---"
        ),
        "40-mask": access(
            f"user::rwx,user:{RAUNAK}:--x,group::---,mask::--x,other::---"
        ),
        "40-mask/masked.txt": access(
            f"user::rw-,user:{RAUNAK}:r--,group::---,mask::---,other::---"
        ),
        "50-other": access("user::rwx,group::---,other::--x"),
        "50-other/other-readable.txt": access("user::rw-,group::---,other::r--"),
        "55-other-no-traverse": access("user::rwx,group::---,other::---"),
        "55-other-no-traverse/other-blocked.txt": access(
            "user::rw-,group::---,other::r--"
        ),
        "60-other-minus-group": access("user::rwx,group::---,other::--x"),
        "60-other-minus-group/other-minus-group-a.txt": access(
            f"user::rw-,group::---,group:{GROUP_A}:---,mask::---,other::r--"
        ),
        "70-no-traverse": access("user::rwx,group::---,other::---"),
        "70-no-traverse/no-traverse.txt": access(
            f"user::rw-,user:{RAUNAK}:r--,group::---,mask::r--,other::---"
        ),
        "80-default-only": access(
            f"user::rwx,group::---,other::--x,default:user:{RAUNAK}:r--"
        ),
        "80-default-only/default-only.txt": access(PRIVATE_FILE),
    }


def _resolver(
    acls: dict[str, AzureDataLakeAccessControl], max_expanded_users: int = 25_000
) -> AzureDataLakeAccessResolver:
    return AzureDataLakeAccessResolver(
        fake_ops(acls), ACCOUNT, CONTAINER, max_expanded_users=max_expanded_users
    )


def _walk(acls: dict[str, AzureDataLakeAccessControl]) -> dict[str, ExternalAccess]:
    """One listing page with every path, parents first."""
    paths = [
        directory(name) if not name.endswith(".txt") else file(name)
        for name in sorted(acls)
        if name
    ]
    return _resolver(acls).page_access(paths)


@pytest.mark.parametrize(
    ("path", "extra_emails", "extra_groups"),
    [
        ("00-private/private.txt", set(), set()),
        ("10-named-user/named-user.txt", {"raunak@onyx.app"}, set()),
        ("20-group-a/group-a.txt", set(), {GROUP_A}),
        # Traverse through group A and read through group B: only members of
        # both read it.
        ("30-cross-group/cross-group.txt", {"raunak@onyx.app"}, set()),
        ("40-mask/masked.txt", set(), set()),
        ("55-other-no-traverse/other-blocked.txt", set(), set()),
        ("70-no-traverse/no-traverse.txt", set(), set()),
        ("80-default-only/default-only.txt", set(), set()),
    ],
)
def test_fixture_matrix(
    path: str, extra_emails: set[str], extra_groups: set[str]
) -> None:
    result: ExternalAccess = _walk(_matrix())[path]

    assert result.external_user_emails == BASE_EMAILS | extra_emails
    assert result.external_user_group_ids == BASE_GROUPS | extra_groups
    assert not result.is_public


def test_other_is_the_tenant_everyone_group() -> None:
    result: ExternalAccess = _walk(_matrix())["50-other/other-readable.txt"]

    # The tenant holds the owner and the RBAC group's members.
    assert result.external_user_emails == set()
    assert result.external_user_group_ids == {EVERYONE_GROUP}


def test_other_minus_a_group_expands_to_the_tenant_without_its_members() -> None:
    result: ExternalAccess = _walk(_matrix())[
        "60-other-minus-group/other-minus-group-a.txt"
    ]

    # Raunak is in group A; the disabled account cannot sign in; the guest is
    # known by their mail.
    assert result.external_user_emails == {
        "owner@onyx.app",
        "subash@onyx.app",
        "admin@onyx.app",
        "guest@example.com",
    }
    assert result.external_user_group_ids == BASE_GROUPS


def test_expansion_over_the_cap_fails_closed() -> None:
    acls = _matrix()
    resolver = _resolver(acls, max_expanded_users=2)
    name = "60-other-minus-group/other-minus-group-a.txt"

    result = resolver.page_access([directory("60-other-minus-group"), file(name)])[name]

    assert result.external_user_emails == set()
    assert result.external_user_group_ids == set()
    assert not result.is_public


def test_walk_across_pages_reads_missing_ancestors_again() -> None:
    acls = _matrix()
    resolver = _resolver(acls)
    resolver.page_access([directory("20-group-a")])
    resolver.page_access([directory("30-cross-group")])

    # The next page starts inside a directory the walk already left.
    result = resolver.page_access([file("20-group-a/group-a.txt")])[
        "20-group-a/group-a.txt"
    ]

    assert result.external_user_group_ids == BASE_GROUPS | {GROUP_A}


def test_deleted_path_stays_private() -> None:
    acls = _matrix()
    del acls["00-private/private.txt"]

    result = _resolver(acls).page_access([file("00-private/private.txt")])[
        "00-private/private.txt"
    ]

    # RBAC readers still read it if it comes back; the ACL grants nothing.
    assert result.external_user_emails == BASE_EMAILS
    assert result.external_user_group_ids == BASE_GROUPS


def test_anonymous_container_is_public() -> None:
    ops = fake_ops(_matrix(), anonymous_read=True)
    resolver = AzureDataLakeAccessResolver(ops, ACCOUNT, CONTAINER)

    result = resolver.page_access([file("00-private/private.txt")])[
        "00-private/private.txt"
    ]

    assert result.is_public


def test_account_without_anonymous_access_is_not_public() -> None:
    ops = fake_ops(_matrix(), anonymous_read=True, allow_blob_public_access=False)
    resolver = AzureDataLakeAccessResolver(ops, ACCOUNT, CONTAINER)

    result = resolver.page_access([file("00-private/private.txt")])[
        "00-private/private.txt"
    ]

    assert not result.is_public


def test_container_and_directory_access() -> None:
    acls = _matrix()
    acls[""] = access(f"user::rwx,group::---,group:{GROUP_A}:r-x,mask::r-x,other::--x")
    resolver = _resolver(acls)

    root = resolver.container_access()
    named = resolver.directory_access("10-named-user")

    assert root.external_user_group_ids == BASE_GROUPS | {GROUP_A}
    # Listing needs read on the directory; Raunak has only execute.
    assert named.external_user_emails == BASE_EMAILS
    assert named.external_user_group_ids == BASE_GROUPS


def _granted(
    acl: str, bit: AclBit, owner: str = OWNER, group: str = "$superuser"
) -> PrincipalSet:
    return granted_principals(access(acl, owner=owner, group=group), bit)


def test_owner_class_matches_first() -> None:
    # The owner lacks read, so a group that grants it does not help them.
    granted = _granted(
        f"user::-wx,group::---,group:{GROUP_A}:r--,mask::r--,other::r--",
        AclBit.READ,
    )

    assert granted == frozenset(
        {
            group_term(GROUP_A, excluded_users={OWNER}),
            everyone_term(excluded_users={OWNER}),
        }
    )


def test_named_user_without_the_bit_is_denied_everywhere() -> None:
    granted = _granted(
        f"user::rwx,user:{RAUNAK}:---,group:{GROUP_A}:r--,mask::r--,other::---",
        AclBit.READ,
    )

    assert granted == frozenset(
        {user_term(OWNER), group_term(GROUP_A, excluded_users={RAUNAK})}
    )


def test_group_entries_union_and_do_not_fall_through_to_other() -> None:
    granted = _granted(
        f"user::rwx,group::r--,group:{GROUP_B}:---,mask::r--,other::r--",
        AclBit.READ,
        group=GROUP_A,
    )

    assert granted == frozenset(
        {
            user_term(OWNER),
            group_term(GROUP_A),
            # Members of B match B's entry, unless A also holds them.
            everyone_term(excluded_groups={GROUP_B}),
        }
    )


def test_mask_limits_named_entries_and_owning_group_not_owner_or_other() -> None:
    granted = _granted(
        f"user::r--,user:{RAUNAK}:r--,group::r--,mask::---,other::r--",
        AclBit.READ,
        group=GROUP_A,
    )

    assert granted == frozenset(
        {
            user_term(OWNER),
            everyone_term(excluded_users={RAUNAK}, excluded_groups={GROUP_A}),
        }
    )


def test_default_entries_grant_nothing() -> None:
    granted = _granted(
        f"user::---,group::---,other::---,default:user:{RAUNAK}:rwx,default:other::rwx",
        AclBit.READ,
    )

    assert granted == frozenset()


def test_open_acl_is_everyone() -> None:
    assert _granted("user::rwx,group::r-x,other::r-x", AclBit.EXECUTE) == frozenset(
        {EVERYONE_TERM}
    )


def test_permissions_string_without_acl() -> None:
    no_acl = AzureDataLakeAccessControl(
        owner=OWNER, group="$superuser", permissions="rwxr-----", acl=""
    )

    assert granted_principals(no_acl, AclBit.READ) == frozenset({user_term(OWNER)})


def test_group_shared_by_both_sides_stays_a_group() -> None:
    acls = _matrix()
    resolver = _resolver(acls)

    result = resolver.page_access(
        [directory("20-group-a"), file("20-group-a/group-a.txt")]
    )["20-group-a/group-a.txt"]

    # No user of group A is listed: the group stays whole.
    assert "raunak@onyx.app" not in result.external_user_emails
    assert ADMIN not in result.external_user_emails


def test_unreadable_group_used_as_an_exclusion_fails_closed() -> None:
    acls = _matrix()
    ops = fake_ops(acls)
    members = ops.list_transitive_group_members.side_effect

    def hidden(*, group_id: str, next_link: str | None = None) -> object:
        if group_id == GROUP_A:
            raise InsufficientPermissionsError("hidden membership")
        return members(group_id=group_id, next_link=next_link)

    ops.list_transitive_group_members.side_effect = hidden
    resolver = AzureDataLakeAccessResolver(ops, ACCOUNT, CONTAINER)
    name = "60-other-minus-group/other-minus-group-a.txt"

    result = resolver.page_access([directory("60-other-minus-group"), file(name)])[name]

    # Raunak is in group A, so counting A as empty would let him read.
    assert result.external_user_emails == set()
    assert result.external_user_group_ids == set()


def test_listing_a_directory_needs_execute_on_it() -> None:
    acls = _matrix()
    acls["read-only"] = access("user::rwx,group::---,other::r--")
    resolver = _resolver(acls)

    result = resolver.directory_access("read-only")

    assert result.external_user_group_ids == BASE_GROUPS


def test_sticky_bit_keeps_other_execute() -> None:
    sticky = AzureDataLakeAccessControl(
        owner=OWNER, group="$superuser", permissions="rwxr-x--t", acl=""
    )

    assert granted_principals(sticky, AclBit.EXECUTE) == frozenset({EVERYONE_TERM})
