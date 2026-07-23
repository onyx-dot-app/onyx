"""The unified ``PATCH /admin/apps/{id}`` update path, single-tenant (non-managed,
so config fields are editable): full update, partial update, and push-failure
rollback. The managed (cloud) variant lives in ``test_managed_external_apps.py``.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

import onyx.server.features.build.external_apps.api as api
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import (
    get_external_app_by_id,
    get_skills_for_external_app,
)
from onyx.db.models import ExternalApp, Skill, User
from onyx.server.features.build.external_apps.models import UpdateExternalAppRequest
from tests.external_dependency_unit.craft.db_helpers import (
    make_external_app,
    reset_built_in_skill_row,
)

_AUTH_TEMPLATE = {"Authorization": "Bearer {token}"}
_PATTERNS = ["https://slack.com/api/.*"]


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


@pytest.fixture(autouse=True)
def _clean_slack_rows(db_session: Session) -> Generator[None, None, None]:
    db_session.execute(delete(Skill).where(Skill.name == "slack"))
    db_session.commit()
    yield
    db_session.execute(delete(Skill).where(Skill.name == "slack"))
    db_session.commit()


def _slack_app(db_session: Session) -> ExternalApp:
    skill = reset_built_in_skill_row(
        db_session, built_in_skill_id="slack", is_public=True
    )
    app = make_external_app(
        db_session,
        skill=skill,
        app_type=ExternalAppType.SLACK,
        auth_template=_AUTH_TEMPLATE,
        upstream_url_patterns=_PATTERNS,
    )
    db_session.commit()
    return app


def test_patch_updates_config_on_non_managed_built_in(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "push_skills_for_users", _noop)
    app = _slack_app(db_session)
    app_id = app.id
    [original_skill] = get_skills_for_external_app(db_session, app_id)
    original_skill_description = original_skill.description

    new_patterns = ["https://slack.com/api/chat.postMessage"]
    new_auth = {"Authorization": "Bearer {access_token}"}
    resp = api.update_external_app_admin(
        external_app_id=app_id,
        request=UpdateExternalAppRequest(
            name="Slack — Eng",
            upstream_url_patterns=new_patterns,
            auth_template=new_auth,
            organization_credentials={"shared": "value"},
        ),
        _=test_user,
        db_session=db_session,
    )

    assert resp.name == "Slack — Eng"
    assert resp.upstream_url_patterns == new_patterns
    assert resp.auth_template == new_auth

    db_session.expire_all()
    stored = get_external_app_by_id(db_session, app_id)
    assert stored is not None
    [skill] = get_skills_for_external_app(db_session, app_id)
    assert stored.name == "Slack — Eng"
    assert skill.name == "slack"
    assert skill.description == original_skill_description
    assert list(stored.upstream_url_patterns) == new_patterns
    assert stored.auth_template == new_auth
    assert stored.organization_credentials.get_value(apply_mask=False) == {
        "shared": "value"
    }


def test_patch_rolls_back_when_push_fails(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Push failure leaves the app update uncommitted."""
    app = _slack_app(db_session)
    app_id = app.id
    original_name = app.name

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("push failed")

    monkeypatch.setattr(api, "push_skills_for_users", _boom)

    with pytest.raises(RuntimeError):
        api.update_external_app_admin(
            external_app_id=app_id,
            request=UpdateExternalAppRequest(name="changed"),
            _=test_user,
            db_session=db_session,
        )

    db_session.rollback()
    stored = get_external_app_by_id(db_session, app_id)
    assert stored is not None
    assert stored.name == original_name
