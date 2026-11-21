"""Ext-dep tests for external-app skill content delivery via
``build_skills_fileset_for_user``.

External-app providers are *built-in skills* created on demand: their ``Skill``
row carries a ``built_in_skill_id`` (e.g. ``slack``) so it renders through the
exact same disk-backed path as a seeded built-in. A user gets the content when
the user runs a plugin that holds the app's integration, also before the user
connects the app (``onyx.db.app_skill``).

Uses the real Slack provider directory on disk so the wiring
(``built_in_skill_id -> source dir``) is exercised end to end. The rule itself
is covered by ``test_app_skills_without_link``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType, IntegrationActionPolicyValue
from onyx.db.models import Skill, User
from onyx.external_apps.providers.slack import SlackAction
from onyx.external_apps.providers.zendesk import ZendeskAction
from onyx.server.features.skill.response_helpers import skill_preview_response
from onyx.skills.built_in import SLACK
from onyx.skills.bundle import strip_skill_md_frontmatter
from onyx.skills.push import build_skills_fileset_for_user
from tests.external_dependency_unit.craft.db_helpers import (
    give_app_to_user,
    make_external_app,
    make_user,
    reset_built_in_skill_row,
)

# Slack ships on-disk skill content; require a single user-supplied key.
_AUTH_TEMPLATE = {"Authorization": "Bearer {token}"}
_SLACK_ID = SLACK.built_in_skill_id  # Also the skill name and on-disk directory.


def _slack_skill(db_session: Session) -> Skill:
    """A built-in Slack skill row (name == built_in_skill_id), mirroring what
    ``create_external_app`` makes for a connected Slack app. ``reset_*`` keeps
    it independent of the migration-seeded built-in rows."""
    return reset_built_in_skill_row(
        db_session,
        built_in_skill_id=_SLACK_ID,
    )


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
    give_app_to_user(db_session, app=app, user=user)
    db_session.commit()

    files = build_skills_fileset_for_user(user, db_session)

    # Renders from disk under the stable provider dir, like any built-in.
    assert f"{_SLACK_ID}/SKILL.md" in files
    assert f"{_SLACK_ID}/slack_api.py" in files


def test_denied_action_listed_as_unavailable(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """A Blocked admin policy surfaces the action in the unavailable warning;
    available actions are not listed, and the raw template is never shipped."""
    user = make_user(db_session)
    skill = _slack_skill(db_session)
    app = make_external_app(
        db_session,
        skill=skill,
        app_type=ExternalAppType.SLACK,
        auth_template=_AUTH_TEMPLATE,
        action_policies={
            SlackAction.MESSAGES_WRITE.value: IntegrationActionPolicyValue.BLOCKED
        },
    )
    give_app_to_user(db_session, app=app, user=user)
    db_session.commit()

    files = build_skills_fileset_for_user(user, db_session)

    assert f"{_SLACK_ID}/SKILL.md.template" not in files
    rendered = files[f"{_SLACK_ID}/SKILL.md"].decode("utf-8")
    warning = rendered.split(
        "These actions are unavailable and should not be attempted:", 1
    )[1]
    # The denied write is listed; an available read is not (its "### List
    # channels" usage header lives elsewhere, never as a "- List channels" item).
    assert "- Post a message" in warning
    assert "- List channels" not in warning


def test_no_disabled_actions_omits_section(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """With no Blocked admin policy nothing is unavailable, so the warning section
    is omitted entirely — available actions are never enumerated."""
    user = make_user(db_session)
    skill = _slack_skill(db_session)
    app = make_external_app(
        db_session,
        skill=skill,
        app_type=ExternalAppType.SLACK,
        auth_template=_AUTH_TEMPLATE,
    )
    give_app_to_user(db_session, app=app, user=user)
    db_session.commit()

    files = build_skills_fileset_for_user(user, db_session)

    rendered = files[f"{_SLACK_ID}/SKILL.md"].decode("utf-8")
    # No Blocked policies -> the unavailable-actions warning is omitted entirely.
    assert "unavailable and should not be attempted" not in rendered


def test_zendesk_push_and_preview_share_account_and_action_policy(
    db_session: Session,
    test_user: User,
) -> None:
    skill = reset_built_in_skill_row(db_session, built_in_skill_id="zendesk")
    app = make_external_app(
        db_session,
        skill=skill,
        app_type=ExternalAppType.ZENDESK,
        auth_template={"Authorization": "Bearer {access_token}"},
        organization_credentials={"subdomain": "acme"},
        action_policies={
            ZendeskAction.TICKETS_UPDATE.value: IntegrationActionPolicyValue.BLOCKED
        },
    )
    give_app_to_user(db_session, app=app, user=test_user)
    db_session.commit()

    files = build_skills_fileset_for_user(test_user, db_session)
    preview = skill_preview_response(skill, test_user, db_session)
    instructions = strip_skill_md_frontmatter(files["zendesk/SKILL.md"].decode())

    assert preview.instructions_markdown == instructions
    assert "https://acme.zendesk.com" in instructions
    assert "- Update a ticket" in instructions
    assert "{{" not in instructions
    assert files["zendesk/account.txt"].decode().strip() == "https://acme.zendesk.com"
    assert "zendesk/zendesk_api.py" in files
    assert not any(name.endswith(".template") for name in files)
