import os

import pytest

from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser

ENTERPRISE_SKIP = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)


@ENTERPRISE_SKIP
def test_grant_permission_via_toggle(reset: None) -> None:  # noqa: ARG001
    admin_user: DATestUser = UserManager.create(name="admin_grant")
    basic_user: DATestUser = UserManager.create(name="basic_grant")

    group = UserGroupManager.create(
        name="grant-toggle-group",
        user_ids=[admin_user.id, basic_user.id],
        user_performing_action=admin_user,
    )

    # Grant manage:llms
    resp = UserGroupManager.set_permission(group, "manage:llms", True, admin_user)
    resp.raise_for_status()
    assert resp.json() == {"permission": "manage:llms", "enabled": True}

    # Verify group permissions
    group_perms = UserGroupManager.get_permissions(group, admin_user)
    assert "manage:llms" in group_perms, f"Expected manage:llms in {group_perms}"

    # Verify propagated to user
    user_perms = UserManager.get_permissions(basic_user)
    assert "manage:llms" in user_perms, f"Expected manage:llms in {user_perms}"


@ENTERPRISE_SKIP
def test_revoke_permission_via_toggle(reset: None) -> None:  # noqa: ARG001
    admin_user: DATestUser = UserManager.create(name="admin_revoke")
    basic_user: DATestUser = UserManager.create(name="basic_revoke")

    group = UserGroupManager.create(
        name="revoke-toggle-group",
        user_ids=[admin_user.id, basic_user.id],
        user_performing_action=admin_user,
    )

    # Grant then revoke
    UserGroupManager.set_permission(
        group, "manage:llms", True, admin_user
    ).raise_for_status()
    UserGroupManager.set_permission(
        group, "manage:llms", False, admin_user
    ).raise_for_status()

    # Verify removed from group
    group_perms = UserGroupManager.get_permissions(group, admin_user)
    assert (
        "manage:llms" not in group_perms
    ), f"manage:llms should be gone: {group_perms}"

    # Verify removed from user
    user_perms = UserManager.get_permissions(basic_user)
    assert "manage:llms" not in user_perms, f"manage:llms should be gone: {user_perms}"


@ENTERPRISE_SKIP
def test_idempotent_grant(reset: None) -> None:  # noqa: ARG001
    admin_user: DATestUser = UserManager.create(name="admin_idempotent_grant")

    group = UserGroupManager.create(
        name="idempotent-grant-group",
        user_ids=[admin_user.id],
        user_performing_action=admin_user,
    )

    # Toggle ON twice
    UserGroupManager.set_permission(
        group, "manage:llms", True, admin_user
    ).raise_for_status()
    UserGroupManager.set_permission(
        group, "manage:llms", True, admin_user
    ).raise_for_status()

    group_perms = UserGroupManager.get_permissions(group, admin_user)
    assert (
        group_perms.count("manage:llms") == 1
    ), f"manage:llms should appear exactly once: {group_perms}"


@ENTERPRISE_SKIP
def test_idempotent_revoke(reset: None) -> None:  # noqa: ARG001
    admin_user: DATestUser = UserManager.create(name="admin_idempotent_revoke")

    group = UserGroupManager.create(
        name="idempotent-revoke-group",
        user_ids=[admin_user.id],
        user_performing_action=admin_user,
    )

    # Toggle OFF when never granted — should not error
    resp = UserGroupManager.set_permission(group, "manage:llms", False, admin_user)
    resp.raise_for_status()


@ENTERPRISE_SKIP
def test_cannot_toggle_basic_access(reset: None) -> None:  # noqa: ARG001
    admin_user: DATestUser = UserManager.create(name="admin_basic_block")

    group = UserGroupManager.create(
        name="basic-block-group",
        user_ids=[admin_user.id],
        user_performing_action=admin_user,
    )

    resp = UserGroupManager.set_permission(group, "basic", True, admin_user)
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"


@ENTERPRISE_SKIP
def test_cannot_toggle_admin(reset: None) -> None:  # noqa: ARG001
    admin_user: DATestUser = UserManager.create(name="admin_admin_block")

    group = UserGroupManager.create(
        name="admin-block-group",
        user_ids=[admin_user.id],
        user_performing_action=admin_user,
    )

    resp = UserGroupManager.set_permission(group, "admin", True, admin_user)
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"


@ENTERPRISE_SKIP
def test_implied_permissions_expand(reset: None) -> None:  # noqa: ARG001
    admin_user: DATestUser = UserManager.create(name="admin_implied")
    basic_user: DATestUser = UserManager.create(name="basic_implied")

    group = UserGroupManager.create(
        name="implied-expand-group",
        user_ids=[admin_user.id, basic_user.id],
        user_performing_action=admin_user,
    )

    # Grant manage:agents — should imply add:agents and read:agents
    UserGroupManager.set_permission(
        group, "manage:agents", True, admin_user
    ).raise_for_status()

    user_perms = UserManager.get_permissions(basic_user)
    assert "manage:agents" in user_perms, f"Missing manage:agents: {user_perms}"
    assert "add:agents" in user_perms, f"Missing implied add:agents: {user_perms}"
    assert "read:agents" in user_perms, f"Missing implied read:agents: {user_perms}"
