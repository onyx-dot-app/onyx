"""
Unit tests for onyx.auth.permissions — pure logic and FastAPI dependency.
"""

from unittest.mock import MagicMock

import pytest

from onyx.auth.permissions import ALL_PERMISSIONS
from onyx.auth.permissions import get_effective_permissions
from onyx.auth.permissions import IMPLIED_PERMISSIONS
from onyx.auth.permissions import NON_TOGGLEABLE_PERMISSIONS
from onyx.auth.permissions import require_permission
from onyx.auth.permissions import resolve_effective_permissions
from onyx.db.enums import Permission
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

# ---------------------------------------------------------------------------
# resolve_effective_permissions
# ---------------------------------------------------------------------------


class TestResolveEffectivePermissions:
    def test_empty_set(self) -> None:
        assert resolve_effective_permissions(set()) == set()

    def test_basic_implies_api_surface_scopes(self) -> None:
        result = resolve_effective_permissions({"basic"})
        assert result == {"basic", "read:search", "read:chat", "write:chat"}

    def test_write_chat_implies_read_chat(self) -> None:
        result = resolve_effective_permissions({"write:chat"})
        assert result == {"write:chat", "read:chat"}

    def test_read_search_no_implications(self) -> None:
        result = resolve_effective_permissions({"read:search"})
        assert result == {"read:search"}

    def test_basic_does_not_imply_read_admin(self) -> None:
        """read:admin is admin-only — basic principals must never gain it."""
        assert "read:admin" not in resolve_effective_permissions({"basic"})

    def test_write_chat_does_not_imply_search(self) -> None:
        """The chat write surface must not leak into the search surface."""
        assert "read:search" not in resolve_effective_permissions({"write:chat"})

    def test_single_implication(self) -> None:
        result = resolve_effective_permissions({"add:agents"})
        assert result == {"add:agents", "read:agents"}

    def test_manage_agents_implies_add_and_read(self) -> None:
        """manage:agents directly maps to {add:agents, read:agents}."""
        result = resolve_effective_permissions({"manage:agents"})
        assert result == {"manage:agents", "add:agents", "read:agents"}

    def test_manage_connectors_chain(self) -> None:
        result = resolve_effective_permissions({"manage:connectors"})
        assert result == {"manage:connectors", "add:connectors", "read:connectors"}

    def test_manage_document_sets(self) -> None:
        result = resolve_effective_permissions({"manage:document_sets"})
        assert result == {
            "manage:document_sets",
            "read:document_sets",
            "read:connectors",
        }

    def test_manage_user_groups_implies_all_reads(self) -> None:
        result = resolve_effective_permissions({"manage:user_groups"})
        assert result == {
            "manage:user_groups",
            "read:connectors",
            "read:document_sets",
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
            "read:search",
            "read:chat",
            "write:chat",
            "add:agents",
            "read:agents",
            "manage:connectors",
            "add:connectors",
            "read:connectors",
        }

    def test_toggle_permission_no_implications(self) -> None:
        result = resolve_effective_permissions({"read:agent_analytics"})
        assert result == {"read:agent_analytics"}

    def test_all_permissions_for_admin(self) -> None:
        result = resolve_effective_permissions({"admin"})
        assert len(result) == len(ALL_PERMISSIONS)

    def test_admin_includes_api_surface_scopes(self) -> None:
        result = resolve_effective_permissions({"admin"})
        assert {"read:search", "read:chat", "write:chat", "read:admin"} <= result


# ---------------------------------------------------------------------------
# get_effective_permissions (expands implied at read time)
# ---------------------------------------------------------------------------


class TestGetEffectivePermissions:
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

    def test_basic_expands_to_api_surface_scopes(self) -> None:
        user = MagicMock()
        user.effective_permissions = ["basic"]
        result = get_effective_permissions(user)
        assert result == {
            Permission.BASIC_ACCESS,
            Permission.READ_SEARCH,
            Permission.READ_CHAT,
            Permission.WRITE_CHAT,
        }

    def test_empty_column(self) -> None:
        user = MagicMock()
        user.effective_permissions = []
        result = get_effective_permissions(user)
        assert result == set()


# ---------------------------------------------------------------------------
# require_permission (FastAPI dependency)
# ---------------------------------------------------------------------------


class TestRequirePermission:
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


# ---------------------------------------------------------------------------
# API-surface scope registration (pins the spec, not the impl)
# ---------------------------------------------------------------------------


class TestApiSurfaceScopeRegistration:
    # Hardcoded spec: the complete implied-only set (4 READ_* capability reads
    # + 4 API-surface scopes). Equality, not subset, so an accidentally
    # over-broad set (a real capability made un-grantable) is also caught.
    EXPECTED_IMPLIED = {
        "read:connectors",
        "read:document_sets",
        "read:agents",
        "read:users",
        "read:search",
        "read:chat",
        "write:chat",
        "read:admin",
    }

    def test_implied_set_matches_spec(self) -> None:
        assert {p.value for p in Permission.IMPLIED} == self.EXPECTED_IMPLIED

    def test_non_toggleable_is_implied_plus_basic_and_admin(self) -> None:
        assert {p.value for p in NON_TOGGLEABLE_PERMISSIONS} == (
            self.EXPECTED_IMPLIED | {"basic", "admin"}
        )

    def test_implication_edges_match_spec(self) -> None:
        assert IMPLIED_PERMISSIONS["basic"] == {
            "read:search",
            "read:chat",
            "write:chat",
        }
        assert IMPLIED_PERMISSIONS["write:chat"] == {"read:chat"}
