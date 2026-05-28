"""Ext-dep tests for the admin action-policy lifecycle on built-in external
apps, driven through the ``/admin/apps`` endpoint functions.

These exercise the real provider catalog (Slack) + DB, asserting the
create/edit/read contract:

- storage is dense: every catalog action gets a row, so the stored rows are the
  full source of truth (unset actions persist as ``ASK``);
- supplied ``action_policies`` win for the actions they name and merge over the
  stored set — unmentioned actions keep their stored value (no clobber);
- an omitted map (``None``) or an empty map (``{}``) is a no-op for existing
  choices; clearing an override means sending that action explicitly as ``ASK``;
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
from onyx.external_apps.providers.slack import SlackProvider
from onyx.server.features.build.api.models import ExternalAppAdminResponse
from onyx.server.features.build.api.models import UpsertExternalAppRequest

_AUTH_TEMPLATE = {"Authorization": "Bearer {token}"}

# Derived from the live catalog so these tests track action additions/removals
# instead of hardcoding the current Slack action set.
_CATALOG_IDS = {endpoint.id.value for endpoint in SlackProvider.spec.endpoint_catalog}


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


def _row_count(db_session: Session, app_id: int) -> int:
    """Raw policy-row count (not de-duplicated like ``_stored``), so duplicate
    rows for the same action would be caught."""
    return len(
        db_session.scalars(
            select(ExternalAppPolicy).where(ExternalAppPolicy.external_app_id == app_id)
        ).all()
    )


def test_create_persists_dense_policies_with_unset_as_ask(
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

    # Dense: a row for every catalog action — overrides honoured, the rest ASK.
    stored = _stored(db_session, resp.id)
    assert stored == {
        SlackAction.CHANNELS_READ.value: EndpointPolicy.ASK,
        SlackAction.MESSAGES_READ.value: EndpointPolicy.ALWAYS,
        SlackAction.USERS_READ.value: EndpointPolicy.ASK,
        SlackAction.SEARCH_READ.value: EndpointPolicy.ASK,
        SlackAction.MESSAGES_WRITE.value: EndpointPolicy.DENY,
    }
    # The read view echoes the stored set exactly (one entry per action).
    assert _view(resp) == stored


def test_create_without_policies_seeds_all_ask(
    db_session: Session,
    test_user: User,
) -> None:
    resp = _upsert(db_session, test_user, action_policies=None)

    stored = _stored(db_session, resp.id)
    assert stored  # a row was seeded for every catalog action
    assert len(stored) == len(resp.actions)
    assert all(policy == EndpointPolicy.ASK for policy in stored.values())


def test_edit_merges_overrides_preserving_unmentioned(
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

    # A partial map updates only the actions it names; the prior choices for
    # unmentioned actions are preserved (merge, not full-replace).
    edited = _upsert(
        db_session,
        test_user,
        app_id=created.id,
        action_policies={SlackAction.CHANNELS_READ: EndpointPolicy.ALWAYS},
    )

    view = _view(edited)
    assert view[SlackAction.CHANNELS_READ.value] == EndpointPolicy.ALWAYS
    assert view[SlackAction.MESSAGES_READ.value] == EndpointPolicy.ALWAYS
    assert view[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.DENY
    assert view[SlackAction.USERS_READ.value] == EndpointPolicy.ASK


def test_edit_omitting_or_emptying_policies_preserves_existing(
    db_session: Session,
    test_user: User,
) -> None:
    created = _upsert(
        db_session,
        test_user,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY},
    )

    # Neither an omitted map (enable toggle / rename) nor an explicit empty map
    # may wipe the admin's stored choices.
    for omitted in (None, {}):
        edited = _upsert(
            db_session, test_user, app_id=created.id, action_policies=omitted
        )
        assert _view(edited)[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.DENY


def test_edit_with_explicit_ask_clears_override(
    db_session: Session,
    test_user: User,
) -> None:
    created = _upsert(
        db_session,
        test_user,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY},
    )

    # Clearing an override means naming the action explicitly as ASK.
    edited = _upsert(
        db_session,
        test_user,
        app_id=created.id,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.ASK},
    )

    assert _view(edited)[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.ASK


def test_create_seeds_a_row_for_every_catalog_action(
    db_session: Session,
    test_user: User,
) -> None:
    resp = _upsert(
        db_session,
        test_user,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY},
    )

    stored = _stored(db_session, resp.id)
    # Exactly the catalog — nothing missing, nothing extra...
    assert set(stored) == _CATALOG_IDS
    # ...and one row per action (no duplicates).
    assert _row_count(db_session, resp.id) == len(_CATALOG_IDS)


def test_edit_keeps_full_catalog_dense(
    db_session: Session,
    test_user: User,
) -> None:
    created = _upsert(
        db_session,
        test_user,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY},
    )

    edited = _upsert(
        db_session,
        test_user,
        app_id=created.id,
        action_policies={SlackAction.CHANNELS_READ: EndpointPolicy.ALWAYS},
    )

    stored = _stored(db_session, created.id)
    # The edit keeps the row set complete — every action still present, once.
    assert set(stored) == _CATALOG_IDS
    assert _row_count(db_session, created.id) == len(_CATALOG_IDS)
    # Both overrides persisted; the view echoes the stored rows exactly.
    assert stored[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.DENY
    assert stored[SlackAction.CHANNELS_READ.value] == EndpointPolicy.ALWAYS
    assert _view(edited) == stored


def test_sequential_edits_accumulate_and_stay_dense(
    db_session: Session,
    test_user: User,
) -> None:
    created = _upsert(db_session, test_user, action_policies=None)  # all ASK

    # Three edits, each setting a different action, should accumulate.
    _upsert(
        db_session,
        test_user,
        app_id=created.id,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY},
    )
    _upsert(
        db_session,
        test_user,
        app_id=created.id,
        action_policies={SlackAction.MESSAGES_READ: EndpointPolicy.ALWAYS},
    )
    edited = _upsert(
        db_session,
        test_user,
        app_id=created.id,
        action_policies={SlackAction.CHANNELS_READ: EndpointPolicy.ALWAYS},
    )

    stored = _stored(db_session, created.id)
    # Still exactly the catalog after a sequence of edits — no drift, no dupes.
    assert set(stored) == _CATALOG_IDS
    assert _row_count(db_session, created.id) == len(_CATALOG_IDS)
    # Every override from the sequence survived...
    assert stored[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.DENY
    assert stored[SlackAction.MESSAGES_READ.value] == EndpointPolicy.ALWAYS
    assert stored[SlackAction.CHANNELS_READ.value] == EndpointPolicy.ALWAYS
    # ...and actions never touched stayed ASK.
    assert stored[SlackAction.USERS_READ.value] == EndpointPolicy.ASK
    assert stored[SlackAction.SEARCH_READ.value] == EndpointPolicy.ASK
    assert _view(edited) == stored


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
