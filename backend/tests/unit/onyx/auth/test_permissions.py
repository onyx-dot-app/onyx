"""
Unit tests for onyx.auth.permissions — pure logic and FastAPI dependency.
"""

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import Request

from onyx.auth.permissions import ALL_PERMISSIONS
from onyx.auth.permissions import CE_UNGATED_PERMISSIONS
from onyx.auth.permissions import get_effective_permissions
from onyx.auth.permissions import has_global_permission
from onyx.auth.permissions import has_permission
from onyx.auth.permissions import IMPLIED_PERMISSIONS
from onyx.auth.permissions import NON_TOGGLEABLE_PERMISSIONS
from onyx.auth.permissions import require_permission
from onyx.auth.permissions import resolve_effective_permissions
from onyx.auth.users import get_anonymous_user
from onyx.db.enums import Permission
from onyx.db.enums import PermissionAuthority
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.variable_functionality import global_version


def _request(token_scopes: list[Permission] | None = None) -> Request:
    """Fake request whose state carries (or omits) token scopes.

    Omitted token_scopes mimics session / API-key auth — getattr returns None,
    i.e. no token-side restriction.
    """
    state = SimpleNamespace()
    if token_scopes is not None:
        state.token_scopes = token_scopes
    return cast(Request, SimpleNamespace(state=state))


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
            "read:search",
            "read:chat",
            "write:chat",
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

    def test_admin_includes_api_surface_scopes(self) -> None:
        result = resolve_effective_permissions({"admin"})
        assert {"read:search", "read:chat", "write:chat", "read:admin"} <= result


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
        assert result == {
            Permission.BASIC_ACCESS,
            Permission.READ_SEARCH,
            Permission.READ_CHAT,
            Permission.WRITE_CHAT,
        }

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
        result = await dep(request=_request(), user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_has_required_permission(self) -> None:
        user = MagicMock()
        user.effective_permissions = ["manage:connectors"]

        dep = require_permission(Permission.MANAGE_CONNECTORS)
        result = await dep(request=_request(), user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_implied_permission_passes(self) -> None:
        """manage:connectors implies read:connectors at read time."""
        user = MagicMock()
        user.effective_permissions = ["manage:connectors"]

        dep = require_permission(Permission.READ_CONNECTORS)
        result = await dep(request=_request(), user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_missing_permission_raises(self) -> None:
        user = MagicMock()
        user.effective_permissions = ["basic"]

        dep = require_permission(Permission.MANAGE_CONNECTORS)
        with pytest.raises(OnyxError) as exc_info:
            await dep(request=_request(), user=user)
        assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    @pytest.mark.asyncio
    async def test_empty_permissions_fails(self) -> None:
        user = MagicMock()
        user.effective_permissions = []

        dep = require_permission(Permission.BASIC_ACCESS)
        with pytest.raises(OnyxError):
            await dep(request=_request(), user=user)

    @pytest.mark.asyncio
    async def test_pat_scope_within_user_permissions_passes(self) -> None:
        """A scoped PAT may exercise a permission the user holds and the scope covers."""
        user = MagicMock()
        user.effective_permissions = ["basic"]

        dep = require_permission(Permission.READ_SEARCH)
        result = await dep(request=_request([Permission.READ_SEARCH]), user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_pat_scope_blocks_out_of_scope_permission(self) -> None:
        """A search-scoped PAT is denied a chat-write endpoint even though the user holds it."""
        user = MagicMock()
        user.effective_permissions = ["basic"]

        dep = require_permission(Permission.WRITE_CHAT)
        with pytest.raises(OnyxError) as exc_info:
            await dep(request=_request([Permission.READ_SEARCH]), user=user)
        assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    @pytest.mark.asyncio
    async def test_pat_scope_caps_admin(self) -> None:
        """Token scopes cap even a full admin — a read:admin PAT can't write-admin."""
        user = MagicMock()
        user.effective_permissions = ["admin"]

        dep = require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)
        with pytest.raises(OnyxError):
            await dep(request=_request([Permission.READ_ADMIN]), user=user)

    @pytest.mark.asyncio
    async def test_unrestricted_pat_cannot_exceed_user(self) -> None:
        """Even an unrestricted token can't grant a permission the user lacks (intersection is min)."""
        user = MagicMock()
        user.effective_permissions = ["basic"]

        dep = require_permission(Permission.MANAGE_CONNECTORS)
        with pytest.raises(OnyxError):
            await dep(request=_request(None), user=user)

    @pytest.mark.asyncio
    async def test_pat_scope_closure_applies(self) -> None:
        """A write:chat-scoped token reaches a read:chat route (write:chat implies read:chat)."""
        user = MagicMock()
        user.effective_permissions = ["basic"]

        dep = require_permission(Permission.READ_CHAT)
        result = await dep(request=_request([Permission.WRITE_CHAT]), user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_empty_pat_scopes_deny_all(self) -> None:
        """An explicit empty scope set grants nothing — fail-closed."""
        user = MagicMock()
        user.effective_permissions = ["basic"]

        dep = require_permission(Permission.READ_SEARCH)
        with pytest.raises(OnyxError):
            await dep(request=_request([]), user=user)


class TestAnonymousUserPermissions:
    def test_anonymous_user_resolves_to_basic_scopes(self) -> None:
        assert get_effective_permissions(get_anonymous_user()) == {
            Permission.BASIC_ACCESS,
            Permission.READ_SEARCH,
            Permission.READ_CHAT,
            Permission.WRITE_CHAT,
        }

    @pytest.mark.asyncio
    async def test_allow_anonymous_admits_anonymous_user(self) -> None:
        anon = get_anonymous_user()
        dep = require_permission(Permission.WRITE_CHAT, allow_anonymous=True)
        assert await dep(request=_request(None), user=anon) is anon

    @pytest.mark.asyncio
    async def test_allow_anonymous_still_caps_scoped_token(self) -> None:
        user = MagicMock()
        user.effective_permissions = ["basic"]
        dep = require_permission(Permission.WRITE_CHAT, allow_anonymous=True)
        with pytest.raises(OnyxError) as exc_info:
            await dep(request=_request([Permission.READ_SEARCH]), user=user)
        assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


class TestRequirePermissionScope:
    """GATE 1 wiring: allow_scope admits a scoped group manager (cached flag +
    bundle token, no global grant) while the token cap still applies."""

    def setup_method(self) -> None:
        global_version.set_ee()

    def teardown_method(self) -> None:
        global_version.unset_ee()

    def _manager(self) -> MagicMock:
        user = MagicMock()
        user.effective_permissions = ["basic"]  # no global manage token
        user.is_group_manager = True
        return user

    @pytest.mark.asyncio
    async def test_allow_scope_admits_scoped_manager(self) -> None:
        user = self._manager()
        dep = require_permission(Permission.MANAGE_DOCUMENT_SETS, allow_scope=True)
        assert await dep(request=_request(None), user=user) is user

    @pytest.mark.asyncio
    async def test_default_rejects_scoped_manager(self) -> None:
        # allow_scope off (default) → no behavior change; manager lacks the token.
        user = self._manager()
        dep = require_permission(Permission.MANAGE_DOCUMENT_SETS)
        with pytest.raises(OnyxError):
            await dep(request=_request(None), user=user)

    @pytest.mark.asyncio
    async def test_allow_scope_rejects_non_bundle_token(self) -> None:
        user = self._manager()
        dep = require_permission(Permission.MANAGE_LLMS, allow_scope=True)
        with pytest.raises(OnyxError):
            await dep(request=_request(None), user=user)

    @pytest.mark.asyncio
    async def test_allow_scope_rejects_non_manager(self) -> None:
        user = self._manager()
        user.is_group_manager = False
        dep = require_permission(Permission.MANAGE_DOCUMENT_SETS, allow_scope=True)
        with pytest.raises(OnyxError):
            await dep(request=_request(None), user=user)

    @pytest.mark.asyncio
    async def test_allow_scope_still_capped_by_token(self) -> None:
        # Scope would admit, but a read:search-scoped PAT can't reach the token.
        user = self._manager()
        dep = require_permission(Permission.MANAGE_DOCUMENT_SETS, allow_scope=True)
        with pytest.raises(OnyxError):
            await dep(request=_request([Permission.READ_SEARCH]), user=user)


class TestHasPermissionAuthority:
    """has_permission is the single 3-state classifier: GLOBAL / SCOPED / NONE."""

    def setup_method(self) -> None:
        global_version.set_ee()

    def teardown_method(self) -> None:
        global_version.unset_ee()

    def _user(self, perms: list[str], is_manager: bool = False) -> MagicMock:
        user = MagicMock()
        user.effective_permissions = perms
        user.is_group_manager = is_manager
        return user

    def test_global_when_held_outright(self) -> None:
        user = self._user(["manage:document_sets"])
        assert (
            has_permission(user, Permission.MANAGE_DOCUMENT_SETS)
            is PermissionAuthority.GLOBAL
        )

    def test_global_for_admin_on_any_token(self) -> None:
        user = self._user(["admin"])
        assert (
            has_permission(user, Permission.MANAGE_LLMS) is PermissionAuthority.GLOBAL
        )

    def test_scoped_when_manager_holds_only_via_bundle(self) -> None:
        user = self._user(["basic"], is_manager=True)
        assert (
            has_permission(user, Permission.MANAGE_DOCUMENT_SETS)
            is PermissionAuthority.SCOPED
        )

    def test_none_when_manager_but_token_not_in_bundle(self) -> None:
        user = self._user(["basic"], is_manager=True)
        assert has_permission(user, Permission.MANAGE_LLMS) is PermissionAuthority.NONE

    def test_none_when_not_manager_and_not_held(self) -> None:
        user = self._user(["basic"], is_manager=False)
        assert (
            has_permission(user, Permission.MANAGE_DOCUMENT_SETS)
            is PermissionAuthority.NONE
        )

    def test_global_outranks_scoped(self) -> None:
        # holds the token globally AND is a manager → GLOBAL wins
        user = self._user(["manage:document_sets"], is_manager=True)
        assert (
            has_permission(user, Permission.MANAGE_DOCUMENT_SETS)
            is PermissionAuthority.GLOBAL
        )

    def test_has_global_permission_true_only_for_global(self) -> None:
        holder = self._user(["manage:document_sets"])
        assert has_global_permission(holder, Permission.MANAGE_DOCUMENT_SETS) is True
        # SCOPED manager → not global
        manager = self._user(["basic"], is_manager=True)
        assert has_global_permission(manager, Permission.MANAGE_DOCUMENT_SETS) is False
        # NONE → not global
        plain = self._user(["basic"])
        assert has_global_permission(plain, Permission.MANAGE_DOCUMENT_SETS) is False


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
        "read:user_groups",
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
