"""Tests for ee.onyx.external_permissions.box.access.

Regression tests for https://github.com/onyx-dot-app/onyx/issues/17052:
box_sdk_gen deserializes enum-typed fields (role, status, shared link access)
as plain strings, so permission sync crashed with
`AttributeError: 'str' object has no attribute 'value'`.
"""

from box_sdk_gen.schemas.collaboration import Collaboration, CollaborationRoleField
from box_sdk_gen.schemas.file import (
    FileSharedLinkEffectiveAccessField,
    FileSharedLinkEffectivePermissionField,
    FileSharedLinkField,
)
from box_sdk_gen.schemas.group_mini import GroupMini
from box_sdk_gen.schemas.user_collaborations import UserCollaborations

from ee.onyx.external_permissions.box.access import (
    BoxAccessContext,
    apply_collaborations_to_access,
    apply_shared_link_to_access,
)
from onyx.connectors.box.connector import (
    box_all_enterprise_users_group_id,
    box_group_id,
)

_ENTERPRISE_ID = "12345"


def _user_collaboration(
    role: object,
    status: object = "accepted",
    login: str = "Person@Example.com",
) -> Collaboration:
    # role/status are plain strings at runtime despite the enum type hints;
    # tests pass both representations deliberately.
    return Collaboration(
        id="c1",
        type="collaboration",
        role=role,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        accessible_by=UserCollaborations(id="u1", login=login),
    )


class TestApplyCollaborationsToAccess:
    def test_plain_string_role_does_not_crash_and_grants_access(self) -> None:
        access = apply_collaborations_to_access(
            BoxAccessContext(),
            [_user_collaboration(role="editor")],
        )
        assert access.user_emails == {"person@example.com"}

    def test_enum_role_still_grants_access(self) -> None:
        access = apply_collaborations_to_access(
            BoxAccessContext(),
            [_user_collaboration(role=CollaborationRoleField.EDITOR)],
        )
        assert access.user_emails == {"person@example.com"}

    def test_unknown_role_fails_closed(self) -> None:
        access = apply_collaborations_to_access(
            BoxAccessContext(),
            [_user_collaboration(role="some-future-role")],
        )
        assert access.user_emails == set()

    def test_uploader_gets_no_read_access(self) -> None:
        access = apply_collaborations_to_access(
            BoxAccessContext(),
            [_user_collaboration(role="uploader")],
        )
        assert access.user_emails == set()

    def test_pending_collaboration_is_skipped(self) -> None:
        access = apply_collaborations_to_access(
            BoxAccessContext(),
            [_user_collaboration(role="editor", status="pending")],
        )
        assert access.user_emails == set()

    def test_group_collaboration_with_string_role(self) -> None:
        access = apply_collaborations_to_access(
            BoxAccessContext(),
            [
                Collaboration(
                    id="c2",
                    type="collaboration",
                    role="viewer",  # type: ignore[arg-type]
                    status="accepted",  # type: ignore[arg-type]
                    accessible_by=GroupMini(id="g1"),
                )
            ],
        )
        assert access.group_ids == {box_group_id("g1")}


class TestApplySharedLinkToAccess:
    def _shared_link(self, access_value: object) -> FileSharedLinkField:
        return FileSharedLinkField(
            url="https://app.box.com/s/abc",
            effective_access=access_value,  # type: ignore[arg-type]
            effective_permission=FileSharedLinkEffectivePermissionField.CAN_DOWNLOAD,
            is_password_enabled=False,
            download_count=0,
            preview_count=0,
            access=None,
        )

    def test_plain_string_open_link_makes_public(self) -> None:
        access = apply_shared_link_to_access(
            BoxAccessContext(), self._shared_link("open"), _ENTERPRISE_ID
        )
        assert access.is_public is True

    def test_enum_open_link_makes_public(self) -> None:
        access = apply_shared_link_to_access(
            BoxAccessContext(),
            self._shared_link(FileSharedLinkEffectiveAccessField.OPEN),
            _ENTERPRISE_ID,
        )
        assert access.is_public is True

    def test_plain_string_company_link_adds_enterprise_group(self) -> None:
        access = apply_shared_link_to_access(
            BoxAccessContext(), self._shared_link("company"), _ENTERPRISE_ID
        )
        assert access.group_ids == {box_all_enterprise_users_group_id(_ENTERPRISE_ID)}
        assert access.is_public is False

    def test_missing_shared_link_is_noop(self) -> None:
        access = apply_shared_link_to_access(BoxAccessContext(), None, _ENTERPRISE_ID)
        assert access.is_public is False
        assert access.user_emails == set()
