from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

import onyx.server.features.build.external_apps.api as api
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp, Skill, User
from onyx.server.features.build.external_apps.models import (
    CreateBuiltInExternalAppRequest,
    UpdateExternalAppRequest,
    UpsertUserCredentialsRequest,
)
from tests.external_dependency_unit.craft.db_helpers import (
    make_built_in_skill_row,
    make_external_app,
    make_sandbox,
    make_user,
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
    db_session.commit()

    pushed_skill_ids: list[UUID] = []
    monkeypatch.setattr(api, "MULTI_TENANT", False)
    monkeypatch.setattr(
        api,
        "push_skill_to_affected_sandboxes",
        lambda pushed_skill, _db: pushed_skill_ids.append(pushed_skill.id),
    )

    response = api.update_external_app_admin(
        external_app_id=app.id,
        request=UpdateExternalAppRequest(enabled=False),
        _=test_user,
        db_session=db_session,
    )

    assert response.enabled is False
    assert app.enabled is False
    assert pushed_skill_ids == [skill.id]


def test_delete_resolves_affected_users_before_cascade(
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
    db_session.commit()

    calls: list[set[UUID]] = []
    monkeypatch.setattr(api, "MULTI_TENANT", False)
    monkeypatch.setattr(
        api, "push_skills_for_users", lambda user_ids, _db: calls.append(set(user_ids))
    )

    api.delete_external_app_admin(
        external_app_id=app.id,
        _=test_user,
        db_session=db_session,
    )

    assert len(calls) == 1
    assert user.id in calls[0]
    assert api.get_external_app_by_id(db_session, app.id) is None
