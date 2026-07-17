"""Skill visibility (user/admin access-control filter)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import SkillSharePermission
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.db.skill import fetch_skill
from onyx.db.skill import list_skills
from onyx.db.skill import set_skill_public_permission
from onyx.db.skill import SkillAccessPolicy
from tests.external_dependency_unit.craft.db_helpers import add_user_to_group
from tests.external_dependency_unit.craft.db_helpers import make_group
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.db_helpers import share_skill_with_group


def _user_skills(user: User, db_session: Session):
    return list_skills(
        policy=SkillAccessPolicy.VIEW,
        user=user,
        db_session=db_session,
    )


class TestSkillVisibility:
    def test_admin_can_edit_personal_skill(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        admin = make_user(db_session, role=UserRole.ADMIN)
        skill = make_skill(db_session, is_public=False)

        result = fetch_skill(
            skill.id,
            policy=SkillAccessPolicy.EDIT,
            user=admin,
            db_session=db_session,
        )

        assert result is not None
        assert result.id == skill.id

    @pytest.mark.parametrize(
        ("permission", "is_editable"),
        [
            (SkillSharePermission.VIEWER, False),
            (SkillSharePermission.EDITOR, True),
        ],
    )
    def test_group_share_permission_controls_edit_access(
        self,
        permission: SkillSharePermission,
        is_editable: bool,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user = make_user(db_session, role=UserRole.BASIC)
        group = make_group(db_session)
        add_user_to_group(db_session, user, group)
        skill = make_skill(db_session, is_public=False)
        share_skill_with_group(db_session, skill, group, permission)

        result = fetch_skill(
            skill.id,
            policy=SkillAccessPolicy.EDIT,
            user=user,
            db_session=db_session,
        )

        assert (result is not None) is is_editable

    def test_public_permission_null_controls_org_visibility(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user = make_user(db_session, role=UserRole.BASIC)
        skill = make_skill(db_session, is_public=False)
        assert (
            fetch_skill(
                skill.id,
                policy=SkillAccessPolicy.VIEW,
                user=user,
                db_session=db_session,
            )
            is None
        )

        set_skill_public_permission(
            skill=skill,
            public_permission=SkillSharePermission.EDITOR,
            db_session=db_session,
        )
        editor_result = fetch_skill(
            skill.id,
            policy=SkillAccessPolicy.EDIT,
            user=user,
            db_session=db_session,
        )
        assert editor_result is not None
        assert editor_result.id == skill.id

        set_skill_public_permission(
            skill=skill,
            public_permission=None,
            db_session=db_session,
        )
        assert (
            fetch_skill(
                skill.id,
                policy=SkillAccessPolicy.VIEW,
                user=user,
                db_session=db_session,
            )
            is None
        )

    def test_user_loses_skill_after_group_removal(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user = make_user(db_session, role=UserRole.BASIC)
        group = make_group(db_session)
        membership = add_user_to_group(db_session, user, group)
        private_skill = make_skill(db_session, is_public=False)
        share_skill_with_group(db_session, private_skill, group)

        before_ids = {s.id for s in _user_skills(user, db_session)}
        assert private_skill.id in before_ids

        # Yank the user out of the shared group.
        db_session.delete(membership)
        db_session.flush()

        after_ids = {s.id for s in _user_skills(user, db_session)}
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

        # A private skill shared with a group the curator is NOT in.
        other_group = make_group(db_session)
        private_skill = make_skill(db_session, is_public=False)
        share_skill_with_group(db_session, private_skill, other_group)

        # A public skill — both should see it.
        public_skill = make_skill(db_session, is_public=True)

        curator_ids = {s.id for s in _user_skills(curator, db_session)}
        basic_ids = {s.id for s in _user_skills(basic, db_session)}

        # Curator does NOT get admin bypass: invisible private skill is
        # invisible for both.
        assert private_skill.id not in curator_ids
        assert private_skill.id not in basic_ids
        # And the public skill is visible to both.
        assert public_skill.id in curator_ids
        assert public_skill.id in basic_ids

    def test_edit_fetch_allows_curator_for_curated_group_skill(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        curator = make_user(db_session, role=UserRole.CURATOR)
        group = make_group(db_session)
        membership = add_user_to_group(db_session, curator, group)
        membership.is_curator = True
        db_session.flush()
        private_skill = make_skill(db_session, is_public=False)
        share_skill_with_group(db_session, private_skill, group)

        result = fetch_skill(
            private_skill.id,
            policy=SkillAccessPolicy.EDIT,
            user=curator,
            db_session=db_session,
        )

        assert result is not None
        assert result.id == private_skill.id

    def test_edit_fetch_rejects_curator_for_non_curated_group_skill(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        curator = make_user(db_session, role=UserRole.CURATOR)
        group = make_group(db_session)
        add_user_to_group(db_session, curator, group)
        private_skill = make_skill(db_session, is_public=False)
        share_skill_with_group(db_session, private_skill, group)

        result = fetch_skill(
            private_skill.id,
            policy=SkillAccessPolicy.EDIT,
            user=curator,
            db_session=db_session,
        )

        assert result is None

    def test_edit_fetch_rejects_curator_when_shared_outside_curated_groups(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        curator = make_user(db_session, role=UserRole.CURATOR)
        curated_group = make_group(db_session)
        other_group = make_group(db_session)
        membership = add_user_to_group(db_session, curator, curated_group)
        membership.is_curator = True
        db_session.flush()
        private_skill = make_skill(db_session, is_public=False)
        share_skill_with_group(db_session, private_skill, curated_group)
        share_skill_with_group(db_session, private_skill, other_group)

        result = fetch_skill(
            private_skill.id,
            policy=SkillAccessPolicy.EDIT,
            user=curator,
            db_session=db_session,
        )

        assert result is None

    def test_edit_fetch_allows_global_curator_for_member_group_skill(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        curator = make_user(db_session, role=UserRole.GLOBAL_CURATOR)
        group = make_group(db_session)
        add_user_to_group(db_session, curator, group)
        private_skill = make_skill(db_session, is_public=False)
        share_skill_with_group(db_session, private_skill, group)

        result = fetch_skill(
            private_skill.id,
            policy=SkillAccessPolicy.EDIT,
            user=curator,
            db_session=db_session,
        )

        assert result is not None
        assert result.id == private_skill.id

    def test_edit_fetch_rejects_curator_for_public_viewer_skill(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        curator = make_user(db_session, role=UserRole.CURATOR)
        public_skill = make_skill(db_session, is_public=True)

        result = fetch_skill(
            public_skill.id,
            policy=SkillAccessPolicy.EDIT,
            user=curator,
            db_session=db_session,
        )

        assert result is None
