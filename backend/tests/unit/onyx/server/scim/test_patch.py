import pytest

from ee.onyx.server.scim.models import ScimGroupMember
from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimMeta
from ee.onyx.server.scim.models import ScimName
from ee.onyx.server.scim.models import ScimPatchOperation
from ee.onyx.server.scim.models import ScimPatchOperationType
from ee.onyx.server.scim.models import ScimPatchResourceValue
from ee.onyx.server.scim.models import ScimPatchValue
from ee.onyx.server.scim.models import ScimUserResource
from ee.onyx.server.scim.patch import apply_group_patch
from ee.onyx.server.scim.patch import apply_user_patch
from ee.onyx.server.scim.patch import ScimPatchError
from ee.onyx.server.scim.providers.okta import OktaProvider

_OKTA_IGNORED = OktaProvider().ignored_patch_paths


def _make_user(**kwargs: object) -> ScimUserResource:
    defaults: dict = {
        "userName": "test@example.com",
        "active": True,
        "name": ScimName(givenName="Test", familyName="User"),
    }
    defaults.update(kwargs)
    return ScimUserResource(**defaults)


def _make_group(**kwargs: object) -> ScimGroupResource:
    defaults: dict = {"displayName": "Engineering"}
    defaults.update(kwargs)
    return ScimGroupResource(**defaults)


def _replace_op(
    path: str | None = None,
    value: ScimPatchValue = None,
) -> ScimPatchOperation:
    return ScimPatchOperation(op=ScimPatchOperationType.REPLACE, path=path, value=value)


def _add_op(
    path: str | None = None,
    value: ScimPatchValue = None,
) -> ScimPatchOperation:
    return ScimPatchOperation(op=ScimPatchOperationType.ADD, path=path, value=value)


def _remove_op(path: str) -> ScimPatchOperation:
    return ScimPatchOperation(op=ScimPatchOperationType.REMOVE, path=path)


class TestApplyUserPatch:
    """Tests for SCIM user PATCH operations."""

    def test_deactivate_user(self) -> None:
        user = _make_user()
        result = apply_user_patch([_replace_op("active", False)], user)
        assert result.active is False
        assert result.userName == "test@example.com"

    def test_activate_user(self) -> None:
        user = _make_user(active=False)
        result = apply_user_patch([_replace_op("active", True)], user)
        assert result.active is True

    def test_replace_given_name(self) -> None:
        user = _make_user()
        result = apply_user_patch([_replace_op("name.givenName", "NewFirst")], user)
        assert result.name is not None
        assert result.name.givenName == "NewFirst"
        assert result.name.familyName == "User"

    def test_replace_family_name(self) -> None:
        user = _make_user()
        result = apply_user_patch([_replace_op("name.familyName", "NewLast")], user)
        assert result.name is not None
        assert result.name.familyName == "NewLast"

    def test_replace_username(self) -> None:
        user = _make_user()
        result = apply_user_patch([_replace_op("userName", "new@example.com")], user)
        assert result.userName == "new@example.com"

    def test_replace_without_path_uses_dict(self) -> None:
        user = _make_user()
        result = apply_user_patch(
            [
                _replace_op(
                    None,
                    ScimPatchResourceValue(active=False, userName="new@example.com"),
                )
            ],
            user,
        )
        assert result.active is False
        assert result.userName == "new@example.com"

    def test_multiple_operations(self) -> None:
        user = _make_user()
        result = apply_user_patch(
            [
                _replace_op("active", False),
                _replace_op("name.givenName", "Updated"),
            ],
            user,
        )
        assert result.active is False
        assert result.name is not None
        assert result.name.givenName == "Updated"

    def test_case_insensitive_path(self) -> None:
        user = _make_user()
        result = apply_user_patch([_replace_op("Active", False)], user)
        assert result.active is False

    def test_original_not_mutated(self) -> None:
        user = _make_user()
        apply_user_patch([_replace_op("active", False)], user)
        assert user.active is True

    def test_unsupported_path_raises(self) -> None:
        user = _make_user()
        with pytest.raises(ScimPatchError, match="Unsupported path"):
            apply_user_patch([_replace_op("unknownField", "value")], user)

    def test_remove_op_on_user_raises(self) -> None:
        user = _make_user()
        with pytest.raises(ScimPatchError, match="Unsupported operation"):
            apply_user_patch([_remove_op("active")], user)

    def test_replace_without_path_ignores_id(self) -> None:
        """Okta sends 'id' alongside actual changes — it should be silently ignored."""
        user = _make_user()
        result = apply_user_patch(
            [_replace_op(None, ScimPatchResourceValue(active=False, id="some-uuid"))],
            user,
            ignored_paths=_OKTA_IGNORED,
        )
        assert result.active is False

    def test_replace_without_path_ignores_schemas(self) -> None:
        """The 'schemas' key in a value dict should be silently ignored."""
        user = _make_user()
        result = apply_user_patch(
            [
                _replace_op(
                    None,
                    ScimPatchResourceValue(
                        active=False,
                        schemas=["urn:ietf:params:scim:schemas:core:2.0:User"],
                    ),
                )
            ],
            user,
            ignored_paths=_OKTA_IGNORED,
        )
        assert result.active is False

    def test_okta_deactivation_payload(self) -> None:
        """Exact Okta deactivation payload: path-less replace with id + active."""
        user = _make_user()
        result = apply_user_patch(
            [
                _replace_op(
                    None,
                    ScimPatchResourceValue(id="abc-123", active=False),
                )
            ],
            user,
            ignored_paths=_OKTA_IGNORED,
        )
        assert result.active is False
        assert result.userName == "test@example.com"

    def test_replace_displayname(self) -> None:
        user = _make_user()
        result = apply_user_patch(
            [_replace_op("displayName", "New Display Name")], user
        )
        assert result.displayName == "New Display Name"
        assert result.name is not None
        assert result.name.formatted == "New Display Name"

    def test_replace_without_path_complex_value_dict(self) -> None:
        """Okta sends id/schemas/meta alongside actual changes — complex types
        (lists, nested dicts) must not cause Pydantic validation errors."""
        user = _make_user()
        result = apply_user_patch(
            [
                _replace_op(
                    None,
                    ScimPatchResourceValue(
                        active=False,
                        id="some-uuid",
                        schemas=["urn:ietf:params:scim:schemas:core:2.0:User"],
                        meta=ScimMeta(resourceType="User"),
                    ),
                )
            ],
            user,
            ignored_paths=_OKTA_IGNORED,
        )
        assert result.active is False
        assert result.userName == "test@example.com"

    def test_add_operation_works_like_replace(self) -> None:
        user = _make_user()
        result = apply_user_patch([_add_op("externalId", "ext-456")], user)
        assert result.externalId == "ext-456"


class TestApplyGroupPatch:
    """Tests for SCIM group PATCH operations."""

    def test_replace_display_name(self) -> None:
        group = _make_group()
        result, added, removed = apply_group_patch(
            [_replace_op("displayName", "New Name")], group
        )
        assert result.displayName == "New Name"
        assert added == []
        assert removed == []

    def test_add_members(self) -> None:
        group = _make_group()
        result, added, removed = apply_group_patch(
            [
                _add_op(
                    "members",
                    [ScimGroupMember(value="user-1"), ScimGroupMember(value="user-2")],
                )
            ],
            group,
        )
        assert len(result.members) == 2
        assert added == ["user-1", "user-2"]
        assert removed == []

    def test_add_members_without_path(self) -> None:
        group = _make_group()
        result, added, _ = apply_group_patch(
            [_add_op(None, [ScimGroupMember(value="user-1")])],
            group,
        )
        assert len(result.members) == 1
        assert added == ["user-1"]

    def test_add_duplicate_member_skipped(self) -> None:
        group = _make_group(members=[ScimGroupMember(value="user-1")])
        result, added, _ = apply_group_patch(
            [
                _add_op(
                    "members",
                    [ScimGroupMember(value="user-1"), ScimGroupMember(value="user-2")],
                )
            ],
            group,
        )
        assert len(result.members) == 2
        assert added == ["user-2"]

    def test_remove_member(self) -> None:
        group = _make_group(
            members=[
                ScimGroupMember(value="user-1"),
                ScimGroupMember(value="user-2"),
            ]
        )
        result, added, removed = apply_group_patch(
            [_remove_op('members[value eq "user-1"]')],
            group,
        )
        assert len(result.members) == 1
        assert result.members[0].value == "user-2"
        assert removed == ["user-1"]
        assert added == []

    def test_remove_nonexistent_member(self) -> None:
        group = _make_group(members=[ScimGroupMember(value="user-1")])
        result, _, removed = apply_group_patch(
            [_remove_op('members[value eq "user-999"]')],
            group,
        )
        assert len(result.members) == 1
        assert removed == []

    def test_mixed_operations(self) -> None:
        group = _make_group(members=[ScimGroupMember(value="user-1")])
        result, added, removed = apply_group_patch(
            [
                _replace_op("displayName", "Renamed"),
                _add_op("members", [ScimGroupMember(value="user-2")]),
                _remove_op('members[value eq "user-1"]'),
            ],
            group,
        )
        assert result.displayName == "Renamed"
        assert added == ["user-2"]
        assert removed == ["user-1"]
        assert len(result.members) == 1

    def test_remove_without_path_raises(self) -> None:
        group = _make_group()
        with pytest.raises(ScimPatchError, match="requires a path"):
            apply_group_patch(
                [ScimPatchOperation(op=ScimPatchOperationType.REMOVE, path=None)],
                group,
            )

    def test_remove_invalid_path_raises(self) -> None:
        group = _make_group()
        with pytest.raises(ScimPatchError, match="Unsupported remove path"):
            apply_group_patch([_remove_op("displayName")], group)

    def test_replace_members_with_path(self) -> None:
        group = _make_group(
            members=[
                ScimGroupMember(value="user-1"),
                ScimGroupMember(value="user-2"),
            ]
        )
        result, added, removed = apply_group_patch(
            [
                _replace_op(
                    "members",
                    [ScimGroupMember(value="user-2"), ScimGroupMember(value="user-3")],
                )
            ],
            group,
        )
        assert len(result.members) == 2
        member_ids = {m.value for m in result.members}
        assert member_ids == {"user-2", "user-3"}
        assert "user-3" in added
        assert "user-1" in removed
        assert "user-2" not in added
        assert "user-2" not in removed

    def test_replace_members_empty_list_clears(self) -> None:
        group = _make_group(
            members=[
                ScimGroupMember(value="user-1"),
                ScimGroupMember(value="user-2"),
            ]
        )
        result, added, removed = apply_group_patch(
            [_replace_op("members", [])],
            group,
        )
        assert len(result.members) == 0
        assert added == []
        assert set(removed) == {"user-1", "user-2"}

    def test_unsupported_replace_path_raises(self) -> None:
        group = _make_group()
        with pytest.raises(ScimPatchError, match="Unsupported path"):
            apply_group_patch([_replace_op("unknownField", "val")], group)

    def test_original_not_mutated(self) -> None:
        group = _make_group()
        apply_group_patch([_replace_op("displayName", "Changed")], group)
        assert group.displayName == "Engineering"

    def test_replace_without_path_ignores_id(self) -> None:
        """Group replace with 'id' in value dict should be silently ignored."""
        group = _make_group()
        result, _, _ = apply_group_patch(
            [
                _replace_op(
                    None, ScimPatchResourceValue(displayName="Updated", id="some-id")
                )
            ],
            group,
            ignored_paths=_OKTA_IGNORED,
        )
        assert result.displayName == "Updated"

    def test_replace_without_path_ignores_schemas(self) -> None:
        group = _make_group()
        result, _, _ = apply_group_patch(
            [
                _replace_op(
                    None,
                    ScimPatchResourceValue(
                        displayName="Updated",
                        schemas=["urn:ietf:params:scim:schemas:core:2.0:Group"],
                    ),
                )
            ],
            group,
            ignored_paths=_OKTA_IGNORED,
        )
        assert result.displayName == "Updated"

    def test_replace_without_path_complex_value_dict(self) -> None:
        """Group PATCH with complex types in value dict (lists, nested dicts)
        must not cause Pydantic validation errors."""
        group = _make_group()
        result, _, _ = apply_group_patch(
            [
                _replace_op(
                    None,
                    ScimPatchResourceValue(
                        displayName="Updated",
                        id="123",
                        schemas=["urn:ietf:params:scim:schemas:core:2.0:Group"],
                        meta=ScimMeta(resourceType="Group"),
                    ),
                )
            ],
            group,
            ignored_paths=_OKTA_IGNORED,
        )
        assert result.displayName == "Updated"
