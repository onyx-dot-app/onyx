"""App skills with no stored link to the app.

A custom skill of an app is an ordinary plugin: it loads before the user
connects the app and counts for the skill limits. A user gets the built-in
skill of a preset when the user runs a plugin that holds an integration made
from that preset (``onyx.db.app_skill``)."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.db.app_skill import built_in_app_skills
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import delete_external_app
from onyx.db.models import (
    ExternalApp,
    Integration,
    Plugin,
    PluginVersion,
    Skill,
    User,
    UserPluginPreference,
)
from onyx.db.plugin_access import load_user_plugin_states, skill_usage_by_user
from onyx.db.skill import (
    SkillManagementPolicy,
    fetch_skill,
    list_chat_skills,
    list_runtime_skills_for_user,
    list_skills,
    set_skill_enabled_for_user,
    skill_user_states,
)
from onyx.server.features.skill.response_helpers import skills_list_response_for_user
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS
from onyx.skills.models import SkillUsage
from tests.external_dependency_unit.craft.db_helpers import (
    make_app_plugin_for_user,
    make_external_app,
    make_skill,
    make_user,
    reset_built_in_skill_row,
)

_AUTH_TEMPLATE = {"Authorization": "Bearer {token}"}


@pytest.fixture
def session(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[Session, None, None]:
    """Each test writes in one transaction and rolls it back."""
    yield db_session
    db_session.rollback()


def _app_skills(user: User, session: Session) -> dict[str, int]:
    return built_in_app_skills(load_user_plugin_states([user.id], session), session)


def test_custom_app_skill_runs_without_a_connection(session: Session) -> None:
    user = make_user(session)
    skill = make_skill(session, is_public=True)
    make_external_app(session, skill=skill, auth_template=_AUTH_TEMPLATE)
    session.execute(
        update(PluginVersion)
        .where(
            PluginVersion.id
            == select(Plugin.current_version_id)
            .where(Plugin.id == skill.id)
            .scalar_subquery()
        )
        .values(unpacked_size_bytes=1234, file_count=3)
    )
    # The toggle is open with no connection.
    assert skill_user_states(user, [skill.id], session)[skill.id].can_toggle
    set_skill_enabled_for_user(
        skill_id=skill.id, enabled=True, user=user, db_session=session
    )

    states = {
        state.plugin_id: state for state in load_user_plugin_states([user.id], session)
    }
    assert states[skill.id].can_run
    assert skill.name in {s.name for s in list_chat_skills(session, user)}
    assert skill.id in {
        runtime.skill.id
        for runtime in list_runtime_skills_for_user(db_session=session, user=user)
    }
    usage = skill_usage_by_user(
        load_user_plugin_states([user.id], session, runnable_only=True)
    )[user.id]
    without = skill_usage_by_user(
        state
        for state in load_user_plugin_states([user.id], session, runnable_only=True)
        if state.plugin_id != skill.id
    ).get(user.id, SkillUsage())
    assert usage - without == SkillUsage(bytes=1234, files=3)


def test_built_in_app_skill_follows_the_plugin_the_user_runs(
    session: Session,
) -> None:
    runner = make_user(session)
    turned_off = make_user(session)
    no_plugin = make_user(session)
    slack_id = EXTERNAL_APP_BUILT_IN_SKILL_IDS[ExternalAppType.SLACK]
    built_in = reset_built_in_skill_row(session, built_in_skill_id=slack_id)
    app = make_external_app(
        session, app_type=ExternalAppType.SLACK, auth_template=_AUTH_TEMPLATE
    )
    make_app_plugin_for_user(session, app=app, user=runner)
    make_app_plugin_for_user(session, app=app, user=turned_off, enabled=False)

    assert _app_skills(runner, session) == {slack_id: app.id}
    for user in (turned_off, no_plugin):
        assert _app_skills(user, session) == {}

    def runtime(user: User) -> dict[str, int | None]:
        return {
            r.name: r.external_app_id
            for r in list_runtime_skills_for_user(db_session=session, user=user)
            if r.skill.built_in_skill_id is not None
        }

    def viewable(user: User) -> set[str]:
        rows = list_skills(
            policy=SkillManagementPolicy.VIEW, user=user, db_session=session
        )
        listed = {
            skill.name
            for skill in skills_list_response_for_user(rows, user, session).builtins
        }
        fetched = fetch_skill(
            built_in.id,
            policy=SkillManagementPolicy.VIEW,
            user=user,
            db_session=session,
        )
        assert (slack_id in listed) == (fetched is not None)
        return listed

    assert runtime(runner).get(slack_id) == app.id
    assert slack_id in viewable(runner)
    assert skill_user_states(runner, [built_in.id], session)[built_in.id].enabled
    for user in (turned_off, no_plugin):
        assert slack_id not in runtime(user)
        assert slack_id not in viewable(user)
        assert not skill_user_states(user, [built_in.id], session)[built_in.id].enabled


def test_turned_off_integration_gives_no_built_in_skill(session: Session) -> None:
    user = make_user(session)
    slack_id = EXTERNAL_APP_BUILT_IN_SKILL_IDS[ExternalAppType.SLACK]
    reset_built_in_skill_row(session, built_in_skill_id=slack_id)
    custom = make_skill(session, is_public=True)
    app = make_external_app(
        session,
        skill=custom,
        app_type=ExternalAppType.SLACK,
        auth_template=_AUTH_TEMPLATE,
    )
    set_skill_enabled_for_user(
        skill_id=custom.id, enabled=True, user=user, db_session=session
    )
    assert _app_skills(user, session) == {slack_id: app.id}

    session.execute(
        update(Integration)
        .where(Integration.external_app_id == app.id)
        .values(enabled=False)
    )

    assert _app_skills(user, session) == {}
    runtime = {
        r.skill.id: r.name
        for r in list_runtime_skills_for_user(db_session=session, user=user)
    }
    assert custom.id in runtime
    assert slack_id not in runtime.values()


def _free_built_in_app_type(session: Session) -> ExternalAppType:
    used = set(session.scalars(select(ExternalApp.app_type)))
    for app_type in EXTERNAL_APP_BUILT_IN_SKILL_IDS:
        if app_type not in used:
            return app_type
    pytest.skip("Each built-in app type has an app in this database.")


def test_app_delete_keeps_custom_skill_plugins(session: Session) -> None:
    user = make_user(session)
    skill = make_skill(session, is_public=True)
    app = make_external_app(session, skill=skill, auth_template=_AUTH_TEMPLATE)
    set_skill_enabled_for_user(
        skill_id=skill.id, enabled=True, user=user, db_session=session
    )

    delete_external_app(session, app.id)

    assert session.get(Plugin, skill.id) is not None
    assert session.get(Skill, skill.id) is not None
    assert session.scalar(
        select(UserPluginPreference.enabled).where(
            UserPluginPreference.user_id == user.id,
            UserPluginPreference.plugin_id == skill.id,
        )
    )
    assert skill.id in {
        runtime.skill.id
        for runtime in list_runtime_skills_for_user(db_session=session, user=user)
    }


def test_app_delete_removes_the_built_in_row(session: Session) -> None:
    app_type = _free_built_in_app_type(session)
    built_in_skill_id = EXTERNAL_APP_BUILT_IN_SKILL_IDS[app_type]
    reset_built_in_skill_row(session, built_in_skill_id=built_in_skill_id)
    app = make_external_app(session, app_type=app_type, auth_template={})

    delete_external_app(session, app.id)

    assert (
        session.scalar(
            select(Skill.id).where(Skill.built_in_skill_id == built_in_skill_id)
        )
        is None
    )
