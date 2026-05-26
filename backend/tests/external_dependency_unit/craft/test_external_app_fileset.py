"""Ext-dep tests for external-app skill content delivery via
``build_skills_fileset_for_user``.

External-app providers are *built-in skills* created on demand: their ``Skill``
row carries a ``built_in_skill_id`` (e.g. ``slack``) so it renders through the
exact same disk-backed path as a seeded built-in — there is no external-app
special case in the push pipeline. These tests verify that an authenticated,
enabled provider delivers its on-disk content under its stable directory, and
that the gate (``list_skills_for_sandbox_injection``: enabled + per-user
credential completeness) keeps content out otherwise.

Uses the real Slack provider directory on disk so the wiring
(``built_in_skill_id -> source dir``) is exercised end to end. The DB-layer
gate itself is covered separately by ``test_external_app_skill_visibility``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.skills.built_in import SLACK
from onyx.skills.push import build_skills_fileset_for_user
from tests.external_dependency_unit.craft._test_helpers import make_external_app
from tests.external_dependency_unit.craft._test_helpers import make_user
from tests.external_dependency_unit.craft._test_helpers import make_user_credential
from tests.external_dependency_unit.craft._test_helpers import reset_built_in_skill_row

# Slack ships on-disk skill content; require a single user-supplied key.
_AUTH_TEMPLATE = {"Authorization": "Bearer {token}"}
_FULL_CREDS = {"token": "xoxp-test"}
_SLACK_ID = SLACK.built_in_skill_id  # == slug == on-disk dir ("slack")


def _slack_skill(db_session: Session, *, enabled: bool = True) -> Skill:
    """A built-in Slack skill row (slug == built_in_skill_id), mirroring what
    ``create_external_app`` makes for a connected Slack app. ``reset_*`` keeps
    it independent of the migration-seeded built-in rows."""
    return reset_built_in_skill_row(
        db_session,
        built_in_skill_id=_SLACK_ID,
        is_public=True,
        enabled=enabled,
    )


def _has_slack_content(files: dict[str, bytes]) -> bool:
    return f"{_SLACK_ID}/SKILL.md" in files


def test_authenticated_provider_delivers_content_under_stable_dir(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = _slack_skill(db_session)
    app = make_external_app(
        db_session,
        skill=skill,
        app_type=ExternalAppType.SLACK,
        auth_template=_AUTH_TEMPLATE,
    )
    make_user_credential(db_session, app=app, user=user, user_credentials=_FULL_CREDS)
    db_session.commit()

    files = build_skills_fileset_for_user(user, db_session)

    # Renders from disk under the stable provider dir, like any built-in.
    assert f"{_SLACK_ID}/SKILL.md" in files
    assert f"{_SLACK_ID}/slack_api.py" in files


def test_unauthenticated_provider_delivers_nothing(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = _slack_skill(db_session)
    make_external_app(
        db_session,
        skill=skill,
        app_type=ExternalAppType.SLACK,
        auth_template=_AUTH_TEMPLATE,
    )  # no user credential row
    db_session.commit()

    files = build_skills_fileset_for_user(user, db_session)

    assert not _has_slack_content(files)


def test_disabled_provider_delivers_nothing_even_when_authenticated(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = _slack_skill(db_session, enabled=False)
    app = make_external_app(
        db_session,
        skill=skill,
        app_type=ExternalAppType.SLACK,
        auth_template=_AUTH_TEMPLATE,
    )
    make_user_credential(db_session, app=app, user=user, user_credentials=_FULL_CREDS)
    db_session.commit()

    files = build_skills_fileset_for_user(user, db_session)

    assert not _has_slack_content(files)
