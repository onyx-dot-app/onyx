"""The external-apps API must refresh already-running sandboxes on mutation,
the same way the skills admin API does — otherwise a sandbox created *before*
an app is connected (or before a user authenticates) never receives the skill.

These tests call the endpoint functions directly with the push helpers
monkeypatched, asserting each mutation triggers the right push:

- user fills credentials  -> push scoped to the calling user
- admin create/enable     -> push to all affected sandboxes
- admin delete            -> push to users affected *before* the cascade

The push helpers themselves are exercised by ``test_skill_push``; here we only
pin the wiring so it can't silently regress.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Generator
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

import onyx.server.features.build.external_apps.api as api
import onyx.server.features.build.external_apps.oauth as oauth_api
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import set_external_app_organization_credentials
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.server.features.build.external_apps.models import (
    CreateBuiltInExternalAppRequest,
)
from onyx.server.features.build.external_apps.models import OAuthCallbackRequest
from onyx.server.features.build.external_apps.models import UpsertUserCredentialsRequest
from tests.external_dependency_unit.craft.db_helpers import make_external_app
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.db_helpers import reset_built_in_skill_row

_AUTH_TEMPLATE = {"Authorization": "Bearer {token}"}


@pytest.fixture(autouse=True)
def _clean_slack_rows(db_session: Session) -> Generator[None, None, None]:
    """Remove any ``slack`` skill row (cascading its external_app) before and
    after each test, so the slug-unique ``create_external_app`` path doesn't
    collide with a row left by another test."""
    db_session.execute(delete(Skill).where(Skill.slug == "slack"))
    db_session.commit()
    yield
    db_session.execute(delete(Skill).where(Skill.slug == "slack"))
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
    )
    db_session.commit()
    return app


class _RedisStub:
    def __init__(self, key: str, value: bytes) -> None:
        self._key = key
        self._value = value
        self.deleted: list[str] = []

    def get(self, key: str) -> bytes | None:
        if key == self._key:
            return self._value
        return None

    def delete(self, key: str) -> None:
        self.deleted.append(key)


def test_credential_upsert_pushes_to_calling_user_only(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session)
    app = _slack_app(db_session)

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


def test_oauth_callback_pushes_to_calling_user_only(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session)
    app = _slack_app(db_session)
    set_external_app_organization_credentials(
        db_session,
        app,
        {"client_id": "client-id", "client_secret": "client-secret"},
    )
    db_session.commit()

    oauth_uuid = uuid4()
    state = base64.urlsafe_b64encode(oauth_uuid.bytes).rstrip(b"=").decode("ascii")
    redis_key = f"{oauth_api._REDIS_KEY_PREFIX}{oauth_uuid}"
    redis = _RedisStub(
        redis_key,
        json.dumps({"user_id": str(user.id), "external_app_id": app.id}).encode(
            "utf-8"
        ),
    )
    monkeypatch.setattr(oauth_api, "get_redis_client", lambda **_kwargs: redis)

    class _Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "ok": True,
                "authed_user": {
                    "access_token": "xoxp-user",
                    "scope": "channels:read",
                },
            }

    monkeypatch.setattr(
        oauth_api.requests, "post", lambda *_args, **_kwargs: _Response()
    )

    calls: list[set[UUID]] = []
    monkeypatch.setattr(
        oauth_api,
        "push_skills_for_users",
        lambda user_ids, _db: calls.append(set(user_ids)),
    )

    oauth_api.handle_external_app_oauth_callback(
        request=OAuthCallbackRequest(code="code", state=state),
        user=user,
        db_session=db_session,
    )

    assert calls == [{user.id}]
    assert redis.deleted == [redis_key]
    assert db_session.scalar(
        select(ExternalAppUserCredential).where(
            ExternalAppUserCredential.external_app_id == app.id,
            ExternalAppUserCredential.user_id == user.id,
        )
    )


def test_create_pushes_to_affected_sandboxes(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pushed: list[Skill] = []
    monkeypatch.setattr(
        api,
        "push_skill_to_affected_sandboxes",
        lambda skill, _db: pushed.append(skill),
    )

    api.create_built_in_external_app(
        request=CreateBuiltInExternalAppRequest(
            name="Slack",
            description="Slack",
            enabled=True,
            app_type=ExternalAppType.SLACK,
            upstream_url_patterns=[],
            auth_template=_AUTH_TEMPLATE,
            organization_credentials={},
        ),
        _=test_user,
        db_session=db_session,
    )

    assert len(pushed) == 1
    assert pushed[0].built_in_skill_id == "slack"


def test_delete_pushes_to_affected_users_before_cascade(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _slack_app(db_session)
    app_id = app.id

    calls: list[set[UUID]] = []
    monkeypatch.setattr(
        api, "push_skills_for_users", lambda user_ids, _db: calls.append(set(user_ids))
    )

    api.delete_external_app_admin(
        external_app_id=app_id,
        _=test_user,
        db_session=db_session,
    )

    # Push fired exactly once (affected set resolved pre-delete; empty here
    # since no running sandboxes exist in this test).
    assert len(calls) == 1
    assert api.get_external_app_by_id(db_session, app_id) is None
