"""
Unit tests for onyx.auth.permissions — pure logic and FastAPI dependency.
"""

from unittest.mock import MagicMock

import pytest

from onyx.auth.permissions import ALL_PERMISSIONS
from onyx.auth.permissions import CE_UNGATED_PERMISSIONS
from onyx.auth.permissions import get_effective_permissions
from onyx.auth.permissions import require_permission
from onyx.auth.permissions import resolve_effective_permissions
from onyx.db.enums import Permission
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.variable_functionality import global_version

# ---------------------------------------------------------------------------
# resolve_effective_permissions
# ---------------------------------------------------------------------------


class TestResolveEffectivePermissions:
    def test_empty_set(self) -> None:
        assert resolve_effective_permissions(set()) == set()

    def test_basic_no_implications(self) -> None:
        result = resolve_effective_permissions({"basic"})
        assert result == {"basic"}

    def test_single_implication(self) -> None:
        result = resolve_effective_permissions({"add:agents"})
        assert result == {"add:agents", "read:agents"}

    def test_manage_agents_implies_add_and_reads(self) -> None:
        """manage:agents implies add:agents, read:agents, and read:document_sets."""
        result = resolve_effective_permissions({"manage:agents"})
        assert result == {
            "manage:agents",
            "add:agents",
            "read:agents",
            "read:document_sets",
        }

    def test_manage_connectors_chain(self) -> None:
        result = resolve_effective_permissions({"manage:connectors"})
        assert result == {"manage:connectors", "read:connectors"}

    def test_manage_document_sets(self) -> None:
        result = resolve_effective_permissions({"manage:document_sets"})
        assert result == {
            "manage:document_sets",
            "read:document_sets",
            "read:connectors",
            "read:user_groups",
        }

    def test_manage_user_groups_implies_all_reads(self) -> None:
        result = resolve_effective_permissions({"manage:user_groups"})
        assert result == {
            "manage:user_groups",
            "read:connectors",
            "read:document_sets",
            "read:agents",
            "read:users",
            "read:user_groups",
        }

    def test_manage_llms_implies_reads(self) -> None:
        result = resolve_effective_permissions({"manage:llms"})
        assert result == {
            "manage:llms",
            "read:user_groups",
            "read:agents",
            "read:users",
        }

    def test_admin_override(self) -> None:
        result = resolve_effective_permissions({"admin"})
        assert result == set(ALL_PERMISSIONS)

    def test_admin_with_others(self) -> None:
        result = resolve_effective_permissions({"admin", "basic"})
        assert result == set(ALL_PERMISSIONS)

    def test_multi_group_union(self) -> None:
        result = resolve_effective_permissions(
            {"add:agents", "manage:connectors", "basic"}
        )
        assert result == {
            "basic",
            "add:agents",
            "read:agents",
            "manage:connectors",
            "read:connectors",
        }

    def test_toggle_permission_no_implications(self) -> None:
        result = resolve_effective_permissions({"read:agent_analytics"})
        assert result == {"read:agent_analytics"}

    def test_all_permissions_for_admin(self) -> None:
        result = resolve_effective_permissions({"admin"})
        assert len(result) == len(ALL_PERMISSIONS)


# ---------------------------------------------------------------------------
# get_effective_permissions (expands implied at read time)
# ---------------------------------------------------------------------------


class TestGetEffectivePermissions:
    def setup_method(self) -> None:
        """Ensure EE mode is set so CE ungating does not interfere."""
        global_version.set_ee()

    def teardown_method(self) -> None:
        global_version.unset_ee()

    def test_expands_implied_permissions(self) -> None:
        """Column stores only granted; get_effective_permissions expands implied."""
        user = MagicMock()
        user.effective_permissions = ["add:agents"]
        result = get_effective_permissions(user)
        assert result == {Permission.ADD_AGENTS, Permission.READ_AGENTS}

    def test_admin_expands_to_all(self) -> None:
        user = MagicMock()
        user.effective_permissions = ["admin"]
        result = get_effective_permissions(user)
        assert result == set(Permission)

    def test_basic_stays_basic_in_ee(self) -> None:
        user = MagicMock()
        user.effective_permissions = ["basic"]
        result = get_effective_permissions(user)
        assert result == {Permission.BASIC_ACCESS}

    def test_empty_column_in_ee(self) -> None:
        user = MagicMock()
        user.effective_permissions = []
        result = get_effective_permissions(user)
        assert result == set()


class TestCEUngatedPermissions:
    """Verify CE_UNGATED_PERMISSIONS are auto-granted in CE but not in EE."""

    def setup_method(self) -> None:
        global_version.unset_ee()

    def teardown_method(self) -> None:
        global_version.unset_ee()

    def test_basic_user_gets_ungated_permissions_in_ce(self) -> None:
        user = MagicMock()
        user.effective_permissions = ["basic"]
        result = get_effective_permissions(user)
        assert Permission.ADD_AGENTS in result
        assert Permission.READ_AGENTS in result
        assert Permission.BASIC_ACCESS in result

    def test_empty_user_gets_ungated_permissions_in_ce(self) -> None:
        user = MagicMock()
        user.effective_permissions = []
        result = get_effective_permissions(user)
        assert Permission.ADD_AGENTS in result
        assert Permission.READ_AGENTS in result

    def test_basic_user_does_not_get_ungated_permissions_in_ee(self) -> None:
        global_version.set_ee()
        user = MagicMock()
        user.effective_permissions = ["basic"]
        result = get_effective_permissions(user)
        assert Permission.ADD_AGENTS not in result
        assert result == {Permission.BASIC_ACCESS}

    def test_admin_unaffected_by_ce_ungating(self) -> None:
        user = MagicMock()
        user.effective_permissions = ["admin"]
        result = get_effective_permissions(user)
        assert result == set(Permission)

    def test_ce_ungated_set_contains_add_agents(self) -> None:
        assert Permission.ADD_AGENTS in CE_UNGATED_PERMISSIONS


# ---------------------------------------------------------------------------
# require_permission (FastAPI dependency)
# ---------------------------------------------------------------------------


class TestRequirePermission:
    def setup_method(self) -> None:
        global_version.set_ee()

    def teardown_method(self) -> None:
        global_version.unset_ee()

    @pytest.mark.asyncio
    async def test_admin_bypass(self) -> None:
        """Admin stored in column should pass any permission check."""
        user = MagicMock()
        user.effective_permissions = ["admin"]

        dep = require_permission(Permission.MANAGE_CONNECTORS)
        result = await dep(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_has_required_permission(self) -> None:
        user = MagicMock()
        user.effective_permissions = ["manage:connectors"]

        dep = require_permission(Permission.MANAGE_CONNECTORS)
        result = await dep(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_implied_permission_passes(self) -> None:
        """manage:connectors implies read:connectors at read time."""
        user = MagicMock()
        user.effective_permissions = ["manage:connectors"]

        dep = require_permission(Permission.READ_CONNECTORS)
        result = await dep(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_missing_permission_raises(self) -> None:
        user = MagicMock()
        user.effective_permissions = ["basic"]

        dep = require_permission(Permission.MANAGE_CONNECTORS)
        with pytest.raises(OnyxError) as exc_info:
            await dep(user=user)
        assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    @pytest.mark.asyncio
    async def test_empty_permissions_fails(self) -> None:
        user = MagicMock()
        user.effective_permissions = []

        dep = require_permission(Permission.BASIC_ACCESS)
        with pytest.raises(OnyxError):
            await dep(user=user)
