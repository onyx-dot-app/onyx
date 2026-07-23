from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

import onyx.server.features.build.external_apps.api as api
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import (
    get_external_app_by_skill_id,
    get_external_app_user_credential,
)
from onyx.db.models import ExternalApp, Skill, User, UserSkillPreference
from onyx.db.skill import list_runtime_skills_for_user, set_skill_enabled_for_user
from onyx.server.features.build.external_apps.models import (
    CreateBuiltInExternalAppRequest,
    UpdateExternalAppRequest,
    UpsertUserCredentialsRequest,
)
from tests.external_dependency_unit.craft.db_helpers import (
    make_built_in_skill_row,
    make_external_app,
    make_sandbox,
    make_skill,
    make_user,
    make_user_credential,
)


def test_credential_upsert_refreshes_only_the_calling_user(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session)
    skill = make_built_in_skill_row(
        db_session,
        built_in_skill_id=f"credential-push-{uuid4().hex[:8]}",
        is_public=True,
    )
    app = make_external_app(
        db_session,
        skill=skill,
        app_type=ExternalAppType.SLACK,
        auth_template={"Authorization": "Bearer {token}"},
    )
    db_session.commit()

    calls: list[set[UUID]] = []
    monkeypatch.setattr(
        api, "push_skills_for_users", lambda user_ids, _db: calls.append(set(user_ids))
    )

    api.upsert_user_credentials(
        external_app_id=app.id,
        request=UpsertUserCredentialsRequest(user_credentials={"token": "t"}),
        user=user,
        db_session=db_session,
    )

    assert calls == [{user.id}]


def test_disconnect_clears_associated_skill_preferences_only(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session)
    associated_skill = make_skill(
        db_session,
        is_public=True,
        name=f"disconnect-associated-{uuid4().hex[:8]}",
    )
    unrelated_skill = make_skill(
        db_session,
        is_public=True,
        name=f"disconnect-unrelated-{uuid4().hex[:8]}",
    )
    app = make_external_app(
        db_session,
        skill=associated_skill,
        auth_template={"Authorization": "Bearer {token}"},
    )
    make_user_credential(
        db_session,
        app=app,
        user=user,
        user_credentials={"token": "t"},
    )
    for skill in (associated_skill, unrelated_skill):
        set_skill_enabled_for_user(
            skill_id=skill.id,
            user=user,
            enabled=True,
            db_session=db_session,
        )
    db_session.commit()

    calls: list[set[UUID]] = []
    monkeypatch.setattr(
        api,
        "push_skills_for_users",
        lambda user_ids, _db: calls.append(set(user_ids)),
    )

    api.disconnect_user_from_external_app(
        external_app_id=app.id,
        user=user,
        db_session=db_session,
    )

    assert calls == [{user.id}]
    assert (
        get_external_app_user_credential(
            db_session,
            external_app_id=app.id,
            user_id=user.id,
        )
        is None
    )
    assert (
        db_session.get(
            UserSkillPreference,
            {"user_id": user.id, "skill_id": associated_skill.id},
        )
        is None
    )
    assert (
        db_session.get(
            UserSkillPreference,
            {"user_id": user.id, "skill_id": unrelated_skill.id},
        )
        is not None
    )


def test_create_refreshes_the_created_skill(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = make_built_in_skill_row(
        db_session,
        built_in_skill_id=f"create-push-{uuid4().hex[:8]}",
        is_public=True,
    )
    app = make_external_app(
        db_session,
        skill=skill,
        app_type=ExternalAppType.SLACK,
        auth_template={"Authorization": "Bearer {token}"},
    )
    pushed_skill_ids: list[UUID] = []
    monkeypatch.setattr(api, "MULTI_TENANT", False)
    monkeypatch.setattr(api, "create_external_app", lambda **_kwargs: app)

    def _associate_built_in_skill(
        _db: Session,
        _app: ExternalApp,
    ) -> Skill:
        return skill

    monkeypatch.setattr(
        api,
        "associate_built_in_skill__no_commit",
        _associate_built_in_skill,
    )
    monkeypatch.setattr(
        api,
        "push_skill_to_affected_sandboxes",
        lambda pushed_skill, _db: pushed_skill_ids.append(pushed_skill.id),
    )

    api.create_built_in_external_app(
        request=CreateBuiltInExternalAppRequest(
            name="Slack",
            app_type=ExternalAppType.SLACK,
            upstream_url_patterns=[],
            auth_template={"Authorization": "Bearer {token}"},
            organization_credentials={},
        ),
        _=test_user,
        db_session=db_session,
    )

    assert pushed_skill_ids == [skill.id]


def test_admin_toggle_updates_app_and_refreshes_affected_sandboxes(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_sandbox(db_session, test_user)
    skill = make_built_in_skill_row(
        db_session,
        built_in_skill_id=f"toggle-push-{uuid4().hex[:8]}",
        is_public=True,
    )
    app = make_external_app(
        db_session,
        skill=skill,
        app_type=ExternalAppType.SLACK,
        auth_template={"Authorization": "Bearer {token}"},
    )
    second_skill = make_built_in_skill_row(
        db_session,
        built_in_skill_id=f"toggle-push-second-{uuid4().hex[:8]}",
        is_public=True,
    )
    app.associated_skills.append(second_skill)
    db_session.commit()

    calls: list[set[UUID]] = []
    monkeypatch.setattr(api, "MULTI_TENANT", False)
    monkeypatch.setattr(
        api,
        "push_skills_for_users",
        lambda user_ids, _db: calls.append(set(user_ids)),
    )

    response = api.update_external_app_admin(
        external_app_id=app.id,
        request=UpdateExternalAppRequest(enabled=False),
        _=test_user,
        db_session=db_session,
    )

    assert response.enabled is False
    assert app.enabled is False
    assert calls == [{test_user.id}]


def test_delete_removes_provider_skill_and_refreshes_affected_users(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session)
    make_sandbox(db_session, user)
    skill = make_built_in_skill_row(
        db_session,
        built_in_skill_id=f"delete-push-{uuid4().hex[:8]}",
        is_public=True,
    )
    app = make_external_app(
        db_session,
        skill=skill,
        app_type=ExternalAppType.SLACK,
        auth_template={"Authorization": "Bearer {token}"},
    )
    app_id = app.id
    skill_id = skill.id
    db_session.commit()

    calls: list[set[UUID]] = []
    monkeypatch.setattr(api, "MULTI_TENANT", False)
    monkeypatch.setattr(
        api, "push_skills_for_users", lambda user_ids, _db: calls.append(set(user_ids))
    )

    api.delete_external_app_admin(
        external_app_id=app_id,
        _=test_user,
        db_session=db_session,
    )

    assert len(calls) == 1
    assert user.id in calls[0]
    assert api.get_external_app_by_id(db_session, app_id) is None
    assert db_session.get(Skill, skill_id) is None


def test_delete_detaches_custom_skill_and_clears_enablement(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_sandbox(db_session, test_user)
    skill = make_skill(db_session, is_public=True, name="retained-custom-skill")
    set_skill_enabled_for_user(
        skill_id=skill.id,
        user=test_user,
        enabled=True,
        db_session=db_session,
    )
    app = make_external_app(
        db_session,
        skill=skill,
        app_type=ExternalAppType.CUSTOM,
        auth_template={},
    )
    app_id = app.id
    skill_id = skill.id
    db_session.commit()

    assert skill_id in {
        runtime_skill.id
        for runtime_skill in list_runtime_skills_for_user(
            user=test_user,
            db_session=db_session,
        )
    }

    calls: list[set[UUID]] = []
    monkeypatch.setattr(api, "MULTI_TENANT", False)
    monkeypatch.setattr(
        api, "push_skills_for_users", lambda user_ids, _db: calls.append(set(user_ids))
    )

    api.delete_external_app_admin(
        external_app_id=app_id,
        _=test_user,
        db_session=db_session,
    )

    db_session.expire_all()
    assert calls == [{test_user.id}]
    assert api.get_external_app_by_id(db_session, app_id) is None
    assert db_session.get(Skill, skill_id) is not None
    assert get_external_app_by_skill_id(db_session, skill_id) is None
    assert (
        db_session.get(
            UserSkillPreference,
            {"user_id": test_user.id, "skill_id": skill_id},
        )
        is None
    )
    assert skill_id not in {
        runtime_skill.id
        for runtime_skill in list_runtime_skills_for_user(
            user=test_user,
            db_session=db_session,
        )
    }
