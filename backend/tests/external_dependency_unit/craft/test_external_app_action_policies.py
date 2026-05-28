"""Ext-dep tests for the admin action-policy lifecycle on built-in external
apps, driven through the ``/admin/apps`` endpoint functions.

These exercise the real provider catalog (Slack) + DB, asserting the
create/edit/read contract:

- supplied ``action_policies`` persist and come back in the merged view;
- unset actions resolve to ``ASK`` (merge-on-read);
- a supplied map full-replaces the stored set (empty map clears);
- an omitted map (``None``) leaves stored policies untouched;
- unknown action ids are rejected before anything is written;
- orphan rows (id no longer in the catalog) are silently dropped on read.

The push helper is monkeypatched to a noop; its wiring is covered by
``test_external_app_sandbox_push``.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

import onyx.server.features.build.api.external_apps_api as api
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalAppPolicy
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.slack import SlackAction
from onyx.server.features.build.api.models import ExternalAppAdminResponse
from onyx.server.features.build.api.models import UpsertExternalAppRequest

_AUTH_TEMPLATE = {"Authorization": "Bearer {token}"}


@pytest.fixture(autouse=True)
def _clean_slack_rows(db_session: Session) -> Generator[None, None, None]:
    """Remove any ``slack`` skill row (cascading its external_app + policies)
    before and after each test, so the slug-unique create path doesn't collide
    with a row left by another test."""
    db_session.execute(delete(Skill).where(Skill.slug == "slack"))
    db_session.commit()
    yield
    db_session.execute(delete(Skill).where(Skill.slug == "slack"))
    db_session.commit()


@pytest.fixture(autouse=True)
def _noop_push(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api, "push_skill_to_affected_sandboxes", lambda _skill, _db: None
    )


def _upsert(
    db_session: Session,
    test_user: User,
    *,
    app_id: int | None = None,
    action_policies: dict[str, EndpointPolicy] | None = None,
) -> ExternalAppAdminResponse:
    return api.upsert_external_app(
        request=UpsertExternalAppRequest(
            id=app_id,
            name="Slack",
            description="Slack",
            enabled=True,
            app_type=ExternalAppType.SLACK,
            upstream_url_patterns=[],
            auth_template=_AUTH_TEMPLATE,
            organization_credentials={},
            action_policies=action_policies,
        ),
        _=test_user,
        db_session=db_session,
    )


def _stored(db_session: Session, app_id: int) -> dict[str, EndpointPolicy]:
    rows = db_session.scalars(
        select(ExternalAppPolicy).where(ExternalAppPolicy.external_app_id == app_id)
    ).all()
    return {row.action_id: row.policy for row in rows}


def _view(resp: ExternalAppAdminResponse) -> dict[str, EndpointPolicy]:
    return {action.action_id: action.state for action in resp.actions}


def test_create_persists_overrides_and_merges_unset_to_ask(
    db_session: Session,
    test_user: User,
) -> None:
    resp = _upsert(
        db_session,
        test_user,
        action_policies={
            SlackAction.MESSAGES_READ: EndpointPolicy.ALWAYS,
            SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY,
        },
    )

    # Only the two overrides are stored (sparse).
    assert _stored(db_session, resp.id) == {
        SlackAction.MESSAGES_READ.value: EndpointPolicy.ALWAYS,
        SlackAction.MESSAGES_WRITE.value: EndpointPolicy.DENY,
    }

    # The merged view spans the whole catalog: overrides honoured, the rest ASK.
    view = _view(resp)
    assert view[SlackAction.MESSAGES_READ.value] == EndpointPolicy.ALWAYS
    assert view[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.DENY
    assert view[SlackAction.CHANNELS_READ.value] == EndpointPolicy.ASK
    assert view[SlackAction.USERS_READ.value] == EndpointPolicy.ASK
    # Every catalog action appears exactly once.
    assert len(resp.actions) == len(view)
    assert SlackAction.SEARCH_READ.value in view


def test_create_without_policies_yields_all_ask(
    db_session: Session,
    test_user: User,
) -> None:
    resp = _upsert(db_session, test_user, action_policies=None)

    assert _stored(db_session, resp.id) == {}
    assert resp.actions  # catalog is non-empty
    assert all(action.state == EndpointPolicy.ASK for action in resp.actions)


def test_edit_with_map_replaces_stored_set(
    db_session: Session,
    test_user: User,
) -> None:
    created = _upsert(
        db_session,
        test_user,
        action_policies={
            SlackAction.MESSAGES_READ: EndpointPolicy.ALWAYS,
            SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY,
        },
    )

    edited = _upsert(
        db_session,
        test_user,
        app_id=created.id,
        action_policies={SlackAction.CHANNELS_READ: EndpointPolicy.ALWAYS},
    )

    # Full-replace: the prior two overrides are gone, only the new one remains.
    assert _stored(db_session, created.id) == {
        SlackAction.CHANNELS_READ.value: EndpointPolicy.ALWAYS,
    }
    view = _view(edited)
    assert view[SlackAction.CHANNELS_READ.value] == EndpointPolicy.ALWAYS
    assert view[SlackAction.MESSAGES_READ.value] == EndpointPolicy.ASK
    assert view[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.ASK


def test_edit_omitting_policies_preserves_existing(
    db_session: Session,
    test_user: User,
) -> None:
    created = _upsert(
        db_session,
        test_user,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY},
    )

    # A partial update (e.g. a rename / enable-disable) that omits the field
    # must NOT wipe the admin's stored choices.
    _upsert(db_session, test_user, app_id=created.id, action_policies=None)

    assert _stored(db_session, created.id) == {
        SlackAction.MESSAGES_WRITE.value: EndpointPolicy.DENY,
    }


def test_edit_with_empty_map_clears_overrides(
    db_session: Session,
    test_user: User,
) -> None:
    created = _upsert(
        db_session,
        test_user,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY},
    )

    # An explicit empty map is a deliberate full-replace to "no overrides".
    edited = _upsert(db_session, test_user, app_id=created.id, action_policies={})

    assert _stored(db_session, created.id) == {}
    assert all(action.state == EndpointPolicy.ASK for action in edited.actions)


def test_unknown_action_id_rejected_before_create(
    db_session: Session,
    test_user: User,
) -> None:
    with pytest.raises(OnyxError):
        _upsert(
            db_session,
            test_user,
            action_policies={"slack.not.a.real.action": EndpointPolicy.ALWAYS},
        )

    # Validation runs before any mutation, so nothing was persisted.
    assert db_session.scalar(select(Skill).where(Skill.slug == "slack")) is None


def test_orphan_stored_row_dropped_on_read(
    db_session: Session,
    test_user: User,
) -> None:
    created = _upsert(
        db_session,
        test_user,
        action_policies={SlackAction.MESSAGES_READ: EndpointPolicy.ALWAYS},
    )

    # Simulate a catalog id that was retired after the row was written.
    db_session.add(
        ExternalAppPolicy(
            external_app_id=created.id,
            action_id="slack.retired.action",
            policy=EndpointPolicy.DENY,
        )
    )
    db_session.commit()

    apps = api.list_external_apps_admin(_=test_user, db_session=db_session)
    resp = next(app for app in apps if app.id == created.id)

    view = _view(resp)
    # The live override still resolves; the orphan id is absent from the view.
    assert view[SlackAction.MESSAGES_READ.value] == EndpointPolicy.ALWAYS
    assert "slack.retired.action" not in view
    # But it is still physically stored (drop is read-time only, not a delete).
    assert "slack.retired.action" in _stored(db_session, created.id)
