"""Connecting an app always keeps the credentials; skills that do not fit stay off."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db import skill as skill_db
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.external_app import (
    delete_external_app,
    replace_custom_skill_associations__no_commit,
)
from onyx.db.models import (
    ExternalApp,
    ExternalAppUserCredential,
    Skill,
    User,
    UserSkillLimitBlock,
)
from onyx.db.skill import (
    list_runtime_skills_for_user,
    set_skill_enabled_for_user,
    skill_user_states,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.external_apps.api import (
    disconnect_user_from_external_app,
    upsert_user_credentials,
)
from onyx.server.features.build.external_apps.models import (
    UpsertUserCredentialsRequest,
)
from onyx.skills.limits import SKILL_WRITE_MAX_BYTES, SkillLimit
from tests.external_dependency_unit.craft.db_helpers import make_external_app, make_user
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_write_limit import MIB, sized_skill
from tests.external_dependency_unit.db.test_skill_write_limit import clean as clean

pytestmark = pytest.mark.usefixtures("tenant_context")


def _setup(
    session: Session, *, room: int, policy: Policy = Policy.DEFAULT
) -> tuple[User, Skill, Skill, ExternalApp]:
    user = make_user(session, standard_account=True)
    pad = sized_skill(session, size=SKILL_WRITE_MAX_BYTES - room, author=user)
    app_skill = sized_skill(session, size=2 * MIB, policy=policy)
    app = make_external_app(
        session, skill=app_skill, auth_template={"Authorization": "Bearer {token}"}
    )
    return user, pad, app_skill, app


def _connect(session: Session, user: User, app: ExternalApp) -> list[str]:
    response = upsert_user_credentials(
        app.id,
        UpsertUserCredentialsRequest(user_credentials={"token": "secret"}),
        user,
        session,
    )
    return [str(skill_id) for skill_id in response.skill_limit_blocked_skill_ids]


def _connected(session: Session, user: User, app: ExternalApp) -> bool:
    return (
        session.scalar(
            select(ExternalAppUserCredential.id).where(
                ExternalAppUserCredential.user_id == user.id,
                ExternalAppUserCredential.external_app_id == app.id,
            )
        )
        is not None
    )


def _delivered(session: Session, user: User) -> set[str]:
    return {
        str(skill.id)
        for skill in list_runtime_skills_for_user(db_session=session, user=user)
    }


@pytest.mark.parametrize("policy", [Policy.DEFAULT, Policy.REQUIRED])
def test_connection_over_the_limit_keeps_credentials_and_leaves_skill_off(
    clean: Session, policy: Policy
) -> None:
    user, pad, app_skill, app = _setup(clean, room=MIB, policy=policy)

    assert _connect(clean, user, app) == [str(app_skill.id)]

    assert _connected(clean, user, app)
    state = skill_user_states(user, [app_skill.id], clean)[app_skill.id]
    assert state.skill_limit_block == SkillLimit.BYTES
    assert not state.enabled
    assert state.effective_installation_policy == policy
    assert state.external_app_dependency is not None
    assert state.external_app_dependency.ready
    assert _delivered(clean, user) == {str(pad.id)}

    # Making room and connecting again turns the skill on.
    version = pad.current_version
    assert version is not None
    version.unpacked_size_bytes = MIB
    clean.flush()
    assert _connect(clean, user, app) == []
    assert skill_user_states(user, [app_skill.id], clean)[app_skill.id].enabled
    assert _delivered(clean, user) == {str(pad.id), str(app_skill.id)}


def test_connection_with_room_turns_the_skill_on(clean: Session) -> None:
    user, _, app_skill, app = _setup(clean, room=3 * MIB)

    assert _connect(clean, user, app) == []
    assert skill_user_states(user, [app_skill.id], clean)[app_skill.id].enabled


@pytest.mark.parametrize(
    ("limit", "pad"),
    [(SkillLimit.BYTES, 390), (SkillLimit.BYTES, 500), (SkillLimit.FILES, 390)],
)
def test_room_freed_by_a_later_skill_admits_an_earlier_one(
    clean: Session, limit: SkillLimit, pad: int
) -> None:
    """A smaller app Skill that replaces a larger one of its name makes room."""
    user = make_user(clean, standard_account=True)
    suffix = uuid4().hex[:8]

    def skill(amount: int, name: str, author: User | None = None) -> Skill:
        by_bytes = limit == SkillLimit.BYTES
        return sized_skill(
            clean,
            size=amount * MIB if by_bytes else 1,
            files=1 if by_bytes else amount * 10,
            author=author,
            name=f"{name}-{suffix}",
        )

    # 500 is the user's usage limit in MiB, or in tens of files.
    skill(pad, "pad", user)
    fallback = skill(100, "zulu", user)
    alpha, beta, zulu = skill(20, "alpha"), skill(100, "beta"), skill(1, "zulu")
    app = make_external_app(
        clean, skill=alpha, auth_template={"Authorization": "Bearer {token}"}
    )
    app.associated_skills.extend([beta, zulu])
    clean.flush()

    assert _connect(clean, user, app) == [str(beta.id)]

    states = skill_user_states(user, [alpha.id, beta.id, zulu.id], clean)
    assert states[alpha.id].enabled and states[zulu.id].enabled
    assert states[beta.id].skill_limit_block == limit
    assert {str(alpha.id), str(zulu.id)} <= _delivered(clean, user)
    assert not {str(beta.id), str(fallback.id)} & _delivered(clean, user)


def test_enable_retries_and_disconnect_clears_a_block(clean: Session) -> None:
    user, pad, app_skill, app = _setup(clean, room=MIB)
    _connect(clean, user, app)

    with pytest.raises(OnyxError) as refused, clean.begin_nested():
        set_skill_enabled_for_user(
            skill_id=app_skill.id, enabled=True, user=user, db_session=clean
        )
    assert refused.value.status_code == 413
    assert clean.get(UserSkillLimitBlock, (user.id, app_skill.id)) is not None

    set_skill_enabled_for_user(
        skill_id=pad.id, enabled=False, user=user, db_session=clean
    )
    set_skill_enabled_for_user(
        skill_id=app_skill.id, enabled=True, user=user, db_session=clean
    )
    assert skill_user_states(user, [app_skill.id], clean)[app_skill.id].enabled

    _connect(clean, user, app)
    disconnect_user_from_external_app(app.id, user, clean)
    assert not _connected(clean, user, app)
    assert (
        clean.scalars(
            select(UserSkillLimitBlock).where(UserSkillLimitBlock.user_id == user.id)
        ).all()
        == []
    )


def test_failed_limit_check_still_connects(
    clean: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _, app_skill, app = _setup(clean, room=MIB)

    def fail(*_: object) -> None:
        raise RuntimeError("limit check unavailable")

    monkeypatch.setattr(skill_db, "skill_limit_violations", fail)

    assert _connect(clean, user, app) == []
    assert _connected(clean, user, app)
    assert clean.get(UserSkillLimitBlock, (user.id, app_skill.id)) is None


@pytest.mark.parametrize(
    "failure_at", ["capture_skill_limit_baseline", "skill_limit_violations"]
)
def test_failed_recheck_clears_old_app_blocks(
    clean: Session, monkeypatch: pytest.MonkeyPatch, failure_at: str
) -> None:
    user, _, app_skill, app = _setup(clean, room=MIB)
    assert _connect(clean, user, app) == [str(app_skill.id)]

    def fail(*_: object, **__: object) -> None:
        raise RuntimeError("usage unavailable during reconnect")

    monkeypatch.setattr(skill_db, failure_at, fail)
    assert _connect(clean, user, app) == []
    assert _connected(clean, user, app)
    assert clean.get(UserSkillLimitBlock, (user.id, app_skill.id)) is None


@pytest.mark.parametrize("remove_app", [False, True])
def test_unlinking_app_skill_clears_its_blocks_only(
    clean: Session, remove_app: bool
) -> None:
    user, _, app_skill, app = _setup(clean, room=MIB)
    assert _connect(clean, user, app) == [str(app_skill.id)]
    other = sized_skill(clean, size=2 * MIB)
    other_app = make_external_app(
        clean, skill=other, auth_template={"Authorization": "Bearer {token}"}
    )
    assert _connect(clean, user, other_app) == [str(other.id)]

    app_id = app.id
    if remove_app:
        delete_external_app(clean, app_id)
    else:
        replace_custom_skill_associations__no_commit(
            clean, external_app_id=app_id, skill_ids=[]
        )

    state = skill_user_states(user, [app_skill.id], clean)[app_skill.id]
    assert state.skill_limit_block is None
    assert state.enabled is not remove_app
    assert clean.get(UserSkillLimitBlock, (user.id, other.id)) is not None
    assert _connected(clean, user, app) is not remove_app
