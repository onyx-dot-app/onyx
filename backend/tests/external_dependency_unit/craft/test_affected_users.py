"""Affected-user join logic (regression net for SHA ``0d71db1b``)."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import OAuthAccount
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.server.features.build.db.sandbox import get_sandbox_user_map
from tests.external_dependency_unit.craft._test_helpers import add_user_to_group
from tests.external_dependency_unit.craft._test_helpers import grant_skill_to_group
from tests.external_dependency_unit.craft._test_helpers import make_group
from tests.external_dependency_unit.craft._test_helpers import make_sandbox
from tests.external_dependency_unit.craft._test_helpers import make_skill
from tests.external_dependency_unit.craft._test_helpers import make_user


class TestAffectedUserIdsForSkill:
    def test_public_skill_returns_every_running_sandbox_user_id(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user_a = make_user(db_session)
        user_b = make_user(db_session)
        user_c = make_user(db_session)
        make_sandbox(db_session, user_a)
        make_sandbox(db_session, user_b)
        make_sandbox(db_session, user_c)
        skill = make_skill(db_session, is_public=True)

        result = affected_user_ids_for_skill(skill, db_session)

        assert user_a.id in result
        assert user_b.id in result
        assert user_c.id in result

    def test_private_skill_returns_only_users_in_granted_groups(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        granted_user = make_user(db_session)
        ungranted_user = make_user(db_session)
        group_granted = make_group(db_session)
        group_other = make_group(db_session)
        add_user_to_group(db_session, granted_user, group_granted)
        add_user_to_group(db_session, ungranted_user, group_other)
        make_sandbox(db_session, granted_user)
        make_sandbox(db_session, ungranted_user)
        skill = make_skill(db_session, is_public=False)
        grant_skill_to_group(db_session, skill, group_granted)

        result = affected_user_ids_for_skill(skill, db_session)

        assert granted_user.id in result
        assert ungranted_user.id not in result

    def test_user_in_two_granted_groups_appears_once(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        user = make_user(db_session)
        group_x = make_group(db_session)
        group_y = make_group(db_session)
        add_user_to_group(db_session, user, group_x)
        add_user_to_group(db_session, user, group_y)
        make_sandbox(db_session, user)
        skill = make_skill(db_session, is_public=False)
        grant_skill_to_group(db_session, skill, group_x)
        grant_skill_to_group(db_session, skill, group_y)

        result = affected_user_ids_for_skill(skill, db_session)

        # `set` semantics — even with two paths through the join, the user
        # is reported exactly once.
        matches = [uid for uid in result if uid == user.id]
        assert len(matches) == 1

    def test_disabled_skill_still_returns_affected_users(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        # Per docstring at db/skill.py:267-275 — `affected_user_ids_for_skill`
        # deliberately does NOT filter on `enabled`. This is required so that
        # when an admin disables a skill, the push pipeline can still target
        # the sandboxes that previously had it (to deliver the new
        # sans-skill fileset).
        user = make_user(db_session)
        group = make_group(db_session)
        add_user_to_group(db_session, user, group)
        make_sandbox(db_session, user)
        skill = make_skill(db_session, is_public=False, enabled=False)
        grant_skill_to_group(db_session, skill, group)

        result = affected_user_ids_for_skill(skill, db_session)

        assert user.id in result

    def test_returns_empty_when_no_running_sandboxes(
        self,
        db_session: Session,
        test_user: User,  # noqa: ARG002
    ) -> None:
        # User in granted group, but with a SLEEPING sandbox (not RUNNING).
        user_sleeping = make_user(db_session)
        user_terminated = make_user(db_session)
        group = make_group(db_session)
        add_user_to_group(db_session, user_sleeping, group)
        add_user_to_group(db_session, user_terminated, group)
        make_sandbox(db_session, user_sleeping, status=SandboxStatus.SLEEPING)
        make_sandbox(db_session, user_terminated, status=SandboxStatus.TERMINATED)
        skill = make_skill(db_session, is_public=False)
        grant_skill_to_group(db_session, skill, group)

        result = affected_user_ids_for_skill(skill, db_session)

        assert user_sleeping.id not in result
        assert user_terminated.id not in result


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
        # Regression for SHA `0d71db1b` — the .unique() fix.
        #
        # ``get_sandbox_user_map`` runs ``select(Sandbox, User).join(User)``.
        # The User model eager-loads ``oauth_accounts`` with ``lazy="joined"``
        # (see ``onyx/db/models.py::User``). Under SQLAlchemy 2.x, a SELECT
        # that yields ORM entities with joined-eager collections must be
        # iterated through ``.unique()`` whenever the underlying join
        # actually fans out — otherwise ``Result.__iter__`` raises
        # ``InvalidRequestError``.
        #
        # Attaching multiple ``OAuthAccount`` rows is the minimal setup that
        # makes the fan-out fire: each row adds a duplicate ``(Sandbox,
        # User)`` tuple via the joined eager load. Without the ``.unique()``
        # call the function raises during iteration; with it, the map has
        # exactly one entry.
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
