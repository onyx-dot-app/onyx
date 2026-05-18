"""Skill visibility (user/admin access-control filter)."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.db.skill import fetch_skill_for_user
from onyx.db.skill import fetch_skill_for_user_by_slug
from onyx.db.skill import list_skills_for_admin
from onyx.db.skill import list_skills_for_user
from tests.external_dependency_unit.craft._test_helpers import add_user_to_group
from tests.external_dependency_unit.craft._test_helpers import grant_skill_to_group
from tests.external_dependency_unit.craft._test_helpers import make_group
from tests.external_dependency_unit.craft._test_helpers import make_skill
from tests.external_dependency_unit.craft._test_helpers import make_user


class TestSkillVisibility:
    def test_admin_sees_disabled_skill(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        admin = make_user(db_session, role=UserRole.ADMIN)
        disabled_skill = make_skill(db_session, enabled=False, is_public=True)

        admin_list = list_skills_for_admin(db_session)
        admin_ids = {s.id for s in admin_list}

        assert disabled_skill.id in admin_ids
        # Sanity: fetched row is actually disabled.
        admin_seen = next(s for s in admin_list if s.id == disabled_skill.id)
        assert admin_seen.enabled is False
        # And the admin path *also* bypasses the user filter — this user
        # exists but does not change what list_skills_for_admin returns.
        assert admin is not None

    def test_user_does_not_see_disabled_skill(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user = make_user(db_session, role=UserRole.BASIC)
        disabled_skill = make_skill(db_session, enabled=False, is_public=True)

        user_list = list_skills_for_user(user, db_session)
        user_ids = {s.id for s in user_list}

        assert disabled_skill.id not in user_ids

    def test_user_sees_public_skill(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user = make_user(db_session, role=UserRole.BASIC)
        public_skill = make_skill(db_session, is_public=True, enabled=True)

        user_list = list_skills_for_user(user, db_session)
        user_ids = {s.id for s in user_list}

        assert public_skill.id in user_ids

    def test_user_does_not_see_private_skill_without_grant(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user = make_user(db_session, role=UserRole.BASIC)
        # Another group exists with the grant; this user is not in it.
        other_group = make_group(db_session)
        private_skill = make_skill(db_session, is_public=False, enabled=True)
        grant_skill_to_group(db_session, private_skill, other_group)

        user_list = list_skills_for_user(user, db_session)
        user_ids = {s.id for s in user_list}

        assert private_skill.id not in user_ids

    def test_user_sees_private_skill_via_group_grant(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user = make_user(db_session, role=UserRole.BASIC)
        group = make_group(db_session)
        add_user_to_group(db_session, user, group)
        private_skill = make_skill(db_session, is_public=False, enabled=True)
        grant_skill_to_group(db_session, private_skill, group)

        user_list = list_skills_for_user(user, db_session)
        user_ids = {s.id for s in user_list}

        assert private_skill.id in user_ids

    def test_user_loses_skill_after_group_removal(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user = make_user(db_session, role=UserRole.BASIC)
        group = make_group(db_session)
        membership = add_user_to_group(db_session, user, group)
        private_skill = make_skill(db_session, is_public=False, enabled=True)
        grant_skill_to_group(db_session, private_skill, group)

        before_ids = {s.id for s in list_skills_for_user(user, db_session)}
        assert private_skill.id in before_ids

        # Yank the user out of the granted group.
        db_session.delete(membership)
        db_session.flush()

        after_ids = {s.id for s in list_skills_for_user(user, db_session)}
        assert private_skill.id not in after_ids

    def test_curator_user_visibility_matches_regular_user(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        # Current behavior pinned: ONLY UserRole.ADMIN bypasses the visibility
        # filter. Curators (and global curators) walk the same path as
        # regular users — no admin-style "see every row" override.
        curator = make_user(db_session, role=UserRole.CURATOR)
        basic = make_user(db_session, role=UserRole.BASIC)

        # A private skill granted to a group the curator is NOT in.
        other_group = make_group(db_session)
        private_skill = make_skill(db_session, is_public=False, enabled=True)
        grant_skill_to_group(db_session, private_skill, other_group)

        # A public skill — both should see it.
        public_skill = make_skill(db_session, is_public=True, enabled=True)

        curator_ids = {s.id for s in list_skills_for_user(curator, db_session)}
        basic_ids = {s.id for s in list_skills_for_user(basic, db_session)}

        # Curator does NOT get admin bypass: invisible private skill is
        # invisible for both.
        assert private_skill.id not in curator_ids
        assert private_skill.id not in basic_ids
        # And the public skill is visible to both.
        assert public_skill.id in curator_ids
        assert public_skill.id in basic_ids

    def test_fetch_skill_for_user_returns_none_when_not_granted(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user = make_user(db_session, role=UserRole.BASIC)
        other_group = make_group(db_session)
        private_skill = make_skill(db_session, is_public=False, enabled=True)
        grant_skill_to_group(db_session, private_skill, other_group)

        result = fetch_skill_for_user(private_skill.id, user, db_session)

        assert result is None

    def test_fetch_skill_by_slug_obeys_visibility(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user = make_user(db_session, role=UserRole.BASIC)
        group = make_group(db_session)
        other_group = make_group(db_session)
        add_user_to_group(db_session, user, group)

        granted_slug = f"granted-{uuid4().hex[:8]}"
        ungranted_slug = f"ungranted-{uuid4().hex[:8]}"
        granted_skill = make_skill(db_session, slug=granted_slug, is_public=False)
        ungranted_skill = make_skill(db_session, slug=ungranted_slug, is_public=False)
        grant_skill_to_group(db_session, granted_skill, group)
        grant_skill_to_group(db_session, ungranted_skill, other_group)

        seen = fetch_skill_for_user_by_slug(granted_slug, user, db_session)
        unseen = fetch_skill_for_user_by_slug(ungranted_slug, user, db_session)

        assert seen is not None
        assert seen.id == granted_skill.id
        assert unseen is None
