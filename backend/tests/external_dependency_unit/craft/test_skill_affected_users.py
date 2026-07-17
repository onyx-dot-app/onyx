from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import OAuthAccount
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.server.features.build.db.sandbox import get_sandbox_user_map
from tests.external_dependency_unit.craft.db_helpers import add_user_to_group
from tests.external_dependency_unit.craft.db_helpers import make_group
from tests.external_dependency_unit.craft.db_helpers import make_sandbox
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.db_helpers import share_skill_with_group
from tests.external_dependency_unit.craft.db_helpers import share_skill_with_user


class TestAffectedUserIdsForSkill:
    def test_public_skill_targets_all_running_sandbox_users(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        running_users = [make_user(db_session), make_user(db_session)]
        sleeping_user = make_user(db_session)
        for user in running_users:
            make_sandbox(db_session, user)
        make_sandbox(db_session, sleeping_user, status=SandboxStatus.SLEEPING)
        skill = make_skill(db_session, is_public=True)

        result = affected_user_ids_for_skill(skill, db_session)

        assert {user.id for user in running_users} <= result
        assert sleeping_user.id not in result

    def test_private_skill_targets_group_and_direct_shares_only(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        group_user = make_user(db_session)
        direct_user = make_user(db_session)
        unshared_user = make_user(db_session)
        group = make_group(db_session)
        add_user_to_group(db_session, group_user, group)
        for user in (group_user, direct_user, unshared_user):
            make_sandbox(db_session, user)
        skill = make_skill(db_session, is_public=False)
        share_skill_with_group(db_session, skill, group)
        share_skill_with_user(db_session, skill, direct_user)

        result = affected_user_ids_for_skill(skill, db_session)

        assert group_user.id in result
        assert direct_user.id in result
        assert unshared_user.id not in result

    def test_private_skill_deduplicates_multiple_share_paths(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user = make_user(db_session)
        group = make_group(db_session)
        add_user_to_group(db_session, user, group)
        make_sandbox(db_session, user)
        skill = make_skill(db_session, is_public=False)
        share_skill_with_group(db_session, skill, group)
        share_skill_with_user(db_session, skill, user)

        result = affected_user_ids_for_skill(skill, db_session)

        assert result == {user.id}


class TestGetSandboxUserMap:
    def test_sandbox_user_map_excludes_non_running_sandboxes(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user_sleeping = make_user(db_session)
        user_terminated = make_user(db_session)
        user_failed = make_user(db_session)
        make_sandbox(db_session, user_sleeping, status=SandboxStatus.SLEEPING)
        make_sandbox(db_session, user_terminated, status=SandboxStatus.TERMINATED)
        make_sandbox(db_session, user_failed, status=SandboxStatus.FAILED)

        result = get_sandbox_user_map(
            [user_sleeping.id, user_terminated.id, user_failed.id],
            db_session,
        )

        assert result == {}

    def test_sandbox_user_map_deduplicates_users_with_eager_loaded_relationships(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        # Joined eager-loaded OAuth accounts fan out the underlying query.
        user = make_user(db_session)
        for i in range(3):
            db_session.add(
                OAuthAccount(
                    id=uuid4(),
                    user_id=user.id,
                    oauth_name=f"provider-{i}",
                    access_token="dummy-access-token",
                    refresh_token="dummy-refresh-token",
                    account_id=f"acct-{uuid4().hex[:8]}",
                    account_email=f"oauth-{i}-{uuid4().hex[:6]}@example.com",
                )
            )
        db_session.flush()
        sandbox = make_sandbox(db_session, user)

        result = get_sandbox_user_map([user.id], db_session)

        assert len(result) == 1
        assert sandbox.id in result
        assert result[sandbox.id].id == user.id
