"""Tests for user file ACL computation, including shared persona access."""

from unittest.mock import MagicMock
from uuid import uuid4

from onyx.access.access import _collect_user_file_access
from onyx.access.access import get_access_for_user_files_impl
from onyx.access.utils import prefix_user_email
from onyx.configs.constants import PUBLIC_DOC_PAT


def _make_user(email: str) -> MagicMock:
    user = MagicMock()
    user.email = email
    user.id = uuid4()
    return user


def _make_persona(
    *,
    owner: MagicMock | None = None,
    shared_users: list[MagicMock] | None = None,
    is_public: bool = False,
    deleted: bool = False,
) -> MagicMock:
    persona = MagicMock()
    persona.deleted = deleted
    persona.is_public = is_public
    persona.user_id = owner.id if owner else None
    persona.user = owner
    persona.users = shared_users or []
    return persona


def _make_user_file(
    *,
    owner: MagicMock | None = None,
    assistants: list[MagicMock] | None = None,
) -> MagicMock:
    uf = MagicMock()
    uf.id = uuid4()
    uf.user = owner
    uf.user_id = owner.id if owner else None
    uf.assistants = assistants or []
    return uf


class TestCollectUserFileAccess:
    def test_owner_only(self) -> None:
        owner = _make_user("owner@test.com")
        uf = _make_user_file(owner=owner)

        emails, is_public = _collect_user_file_access(uf)

        assert emails == {"owner@test.com"}
        assert is_public is False

    def test_shared_persona_adds_users(self) -> None:
        owner = _make_user("owner@test.com")
        shared = _make_user("shared@test.com")
        persona = _make_persona(owner=owner, shared_users=[shared])
        uf = _make_user_file(owner=owner, assistants=[persona])

        emails, is_public = _collect_user_file_access(uf)

        assert emails == {"owner@test.com", "shared@test.com"}
        assert is_public is False

    def test_persona_owner_added(self) -> None:
        """Persona owner (different from file owner) gets access too."""
        file_owner = _make_user("file-owner@test.com")
        persona_owner = _make_user("persona-owner@test.com")
        persona = _make_persona(owner=persona_owner)
        uf = _make_user_file(owner=file_owner, assistants=[persona])

        emails, is_public = _collect_user_file_access(uf)

        assert "file-owner@test.com" in emails
        assert "persona-owner@test.com" in emails

    def test_public_persona_makes_file_public(self) -> None:
        owner = _make_user("owner@test.com")
        persona = _make_persona(owner=owner, is_public=True)
        uf = _make_user_file(owner=owner, assistants=[persona])

        emails, is_public = _collect_user_file_access(uf)

        assert is_public is True
        assert "owner@test.com" in emails

    def test_deleted_persona_ignored(self) -> None:
        owner = _make_user("owner@test.com")
        shared = _make_user("shared@test.com")
        persona = _make_persona(owner=owner, shared_users=[shared], deleted=True)
        uf = _make_user_file(owner=owner, assistants=[persona])

        emails, is_public = _collect_user_file_access(uf)

        assert emails == {"owner@test.com"}
        assert is_public is False

    def test_multiple_personas_combine(self) -> None:
        owner = _make_user("owner@test.com")
        user_a = _make_user("a@test.com")
        user_b = _make_user("b@test.com")
        p1 = _make_persona(owner=owner, shared_users=[user_a])
        p2 = _make_persona(owner=owner, shared_users=[user_b])
        uf = _make_user_file(owner=owner, assistants=[p1, p2])

        emails, is_public = _collect_user_file_access(uf)

        assert emails == {"owner@test.com", "a@test.com", "b@test.com"}

    def test_deduplication(self) -> None:
        owner = _make_user("owner@test.com")
        shared = _make_user("shared@test.com")
        p1 = _make_persona(owner=owner, shared_users=[shared])
        p2 = _make_persona(owner=owner, shared_users=[shared])
        uf = _make_user_file(owner=owner, assistants=[p1, p2])

        emails, _ = _collect_user_file_access(uf)

        assert emails == {"owner@test.com", "shared@test.com"}


class TestGetAccessForUserFiles:
    def test_ownerless_file_is_public(self) -> None:
        """Files with no owner should be public."""
        uf = _make_user_file(owner=None)
        uf.user = None

        db_session = MagicMock()
        db_session.query.return_value.options.return_value.filter.return_value.all.return_value = [
            uf
        ]

        result = get_access_for_user_files_impl([str(uf.id)], db_session)

        access = result[str(uf.id)]
        assert access.is_public is True
        assert len(access.user_emails) == 0

    def test_shared_user_in_acl(self) -> None:
        """Shared persona users should appear in the ACL."""
        owner = _make_user("owner@test.com")
        shared = _make_user("shared@test.com")
        persona = _make_persona(owner=owner, shared_users=[shared])
        uf = _make_user_file(owner=owner, assistants=[persona])

        db_session = MagicMock()
        db_session.query.return_value.options.return_value.filter.return_value.all.return_value = [
            uf
        ]

        result = get_access_for_user_files_impl([str(uf.id)], db_session)

        access = result[str(uf.id)]
        acl = access.to_acl()
        assert prefix_user_email("owner@test.com") in acl
        assert prefix_user_email("shared@test.com") in acl
        assert access.is_public is False

    def test_public_persona_sets_public_acl(self) -> None:
        owner = _make_user("owner@test.com")
        persona = _make_persona(owner=owner, is_public=True)
        uf = _make_user_file(owner=owner, assistants=[persona])

        db_session = MagicMock()
        db_session.query.return_value.options.return_value.filter.return_value.all.return_value = [
            uf
        ]

        result = get_access_for_user_files_impl([str(uf.id)], db_session)

        access = result[str(uf.id)]
        acl = access.to_acl()
        assert PUBLIC_DOC_PAT in acl
