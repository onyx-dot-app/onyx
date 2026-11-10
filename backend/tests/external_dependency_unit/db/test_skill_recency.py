"""Explicit choices and retained shares keep honest ordering timestamps."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import Skill__User, Skill__UserGroup, UserSkillPreference
from onyx.db.skill import (
    SkillRuntimePriority,
    SkillSharingChange,
    enable_new_skill_if_name_available__no_commit,
    list_runtime_skill_candidates_for_user,
    list_runtime_skills_for_user,
    set_skill_enabled_for_user,
    share_skill__no_commit,
)
from tests.external_dependency_unit.craft.db_helpers import make_skill, make_user
from tests.external_dependency_unit.db.test_skill_access_mutations import manager
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")
PAST = datetime(2000, 1, 1, tzinfo=timezone.utc)


def test_enable_updates_recency_but_disable_keeps_it(session: Session) -> None:
    user = make_user(session, standard_account=True)
    skill = make_skill(session, author_user_id=user.id, is_valid=True)
    session.commit()
    set_skill_enabled_for_user(
        skill_id=skill.id, enabled=True, user=user, db_session=session
    )
    preference = session.get(UserSkillPreference, (user.id, skill.id))
    assert preference is not None and preference.enabled_at is not None
    preference.enabled_at = PAST
    session.flush()
    set_skill_enabled_for_user(
        skill_id=skill.id, enabled=False, user=user, db_session=session
    )
    session.refresh(preference)
    assert not preference.enabled and preference.enabled_at == PAST
    set_skill_enabled_for_user(
        skill_id=skill.id, enabled=True, user=user, db_session=session
    )
    session.refresh(preference)
    assert preference.enabled and preference.enabled_at is not None
    assert preference.enabled_at > PAST
    first = preference.enabled_at
    set_skill_enabled_for_user(
        skill_id=skill.id, enabled=True, user=user, db_session=session
    )
    session.refresh(preference)
    assert preference.enabled_at is not None and preference.enabled_at > first


def test_upload_auto_enable_records_only_a_new_choice(session: Session) -> None:
    user = make_user(session, standard_account=True)
    skill = make_skill(session, author_user_id=user.id, is_valid=True)
    assert enable_new_skill_if_name_available__no_commit(skill, user.id, session)
    preference = session.get(UserSkillPreference, (user.id, skill.id))
    assert preference is not None and preference.enabled_at is not None
    preference.enabled_at = PAST
    session.flush()
    assert not enable_new_skill_if_name_available__no_commit(skill, user.id, session)
    session.refresh(preference)
    assert preference.enabled_at == PAST


@pytest.mark.parametrize("original", [None, PAST])
def test_share_changes_preserve_dates_until_access_is_removed(
    session: Session, original: datetime | None
) -> None:
    actor, group = manager(session, global_access=True)
    reader = make_user(session, standard_account=True)
    skill = make_skill(session, author_user_id=actor.id)
    change = SkillSharingChange(
        user_shares={reader.id: SkillSharePermission.VIEWER},
        group_shares={group: SkillSharePermission.VIEWER},
    )
    share_skill__no_commit(skill, change, actor, session)
    assert skill.user_shares[0].created_at is not None
    assert skill.group_shares[0].created_at is not None
    skill.user_shares[0].created_at = original
    skill.group_shares[0].created_at = original
    session.flush()
    share_skill__no_commit(
        skill,
        SkillSharingChange(
            user_shares={reader.id: SkillSharePermission.EDITOR},
            group_shares={group: SkillSharePermission.EDITOR},
            group_installation_policies={group: SkillInstallationPolicy.REQUIRED},
        ),
        actor,
        session,
    )
    assert skill.user_shares[0].created_at == original
    assert skill.group_shares[0].created_at == original
    assert skill.group_shares[0].installation_policy == SkillInstallationPolicy.REQUIRED
    share_skill__no_commit(
        skill, SkillSharingChange(user_shares={}, group_shares={}), actor, session
    )
    share_skill__no_commit(skill, change, actor, session)
    assert skill.user_shares[0].created_at is not None
    assert skill.group_shares[0].created_at is not None
    assert skill.user_shares[0].created_at != original
    assert skill.group_shares[0].created_at != original


def test_migration_keeps_old_dates_unknown_and_defaults_new_shares(
    session: Session,
) -> None:
    actor, group = manager(session, global_access=True)
    reader = make_user(session, standard_account=True)
    skill = make_skill(session, author_user_id=actor.id)
    share_skill__no_commit(
        skill,
        SkillSharingChange(
            user_shares={reader.id: SkillSharePermission.VIEWER},
            group_shares={group: SkillSharePermission.VIEWER},
        ),
        actor,
        session,
    )
    enable_new_skill_if_name_available__no_commit(skill, actor.id, session)
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
    revision = scripts.get_revision("7655ce71767e")
    assert revision is not None
    connection = session.connection()
    with Operations.context(MigrationContext.configure(connection)):
        revision.module.downgrade()
        revision.module.upgrade()
    session.expire_all()
    assert skill.user_shares[0].created_at is None
    assert skill.group_shares[0].created_at is None
    preference = session.get(UserSkillPreference, (actor.id, skill.id))
    assert preference is not None and preference.enabled_at is None
    new_reader = make_user(session, standard_account=True)
    new_share = Skill__User(skill_id=skill.id, user_id=new_reader.id)
    session.add(new_share)
    session.flush()
    assert new_share.created_at is not None
    assert (
        session.scalar(
            select(Skill__UserGroup.created_at).where(
                Skill__UserGroup.skill_id == skill.id
            )
        )
        is None
    )


def test_keep_ranks_use_policy_and_choice_dates_without_reordering_names(
    session: Session,
) -> None:
    user = make_user(session, standard_account=True)
    required = make_skill(
        session,
        author_user_id=user.id,
        is_valid=True,
    )
    default = make_skill(
        session,
        author_user_id=user.id,
        is_valid=True,
    )
    required.installation_policy = SkillInstallationPolicy.REQUIRED
    default.installation_policy = SkillInstallationPolicy.DEFAULT
    choices = [
        make_skill(session, author_user_id=user.id, is_valid=True) for _ in range(3)
    ]
    recent = datetime(2020, 1, 1, tzinfo=timezone.utc)
    for skill, date in zip(choices, (PAST, recent, None), strict=True):
        session.add(
            UserSkillPreference(
                user_id=user.id,
                skill_id=skill.id,
                name=skill.name,
                enabled=True,
                enabled_at=date,
            )
        )
    session.flush()
    candidates = list_runtime_skill_candidates_for_user(db_session=session, user=user)
    original = list_runtime_skills_for_user(
        db_session=session,
        user=user,
        include_fallbacks=True,
    )
    assert [candidate.skill.id for candidate in candidates] == [
        skill.id for skill in original
    ]
    ids = {required.id, default.id, *(skill.id for skill in choices)}
    ranked = sorted(
        (candidate for candidate in candidates if candidate.skill.id in ids),
        key=lambda candidate: candidate.keep_rank,
    )
    assert [candidate.skill.id for candidate in ranked] == [
        required.id,
        choices[1].id,
        choices[0].id,
        choices[2].id,
        default.id,
    ]
    assert [candidate.priority for candidate in ranked] == [
        SkillRuntimePriority.REQUIRED,
        SkillRuntimePriority.ENABLED,
        SkillRuntimePriority.ENABLED,
        SkillRuntimePriority.ENABLED,
        SkillRuntimePriority.DEFAULT,
    ]
