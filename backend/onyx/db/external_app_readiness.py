"""Whether a user has connected the external app that a skill needs.

Below ``onyx.db.plugin`` in the import order, so the plugin access reads can
use it."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from onyx.db.models import ExternalApp, ExternalApp__Skill, ExternalAppUserCredential

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def placeholders_in_template(auth_template: dict[str, Any]) -> set[str]:
    placeholders: set[str] = set()
    for value in auth_template.values():
        if isinstance(value, str):
            placeholders.update(_PLACEHOLDER_RE.findall(value))
    return placeholders


def required_user_credential_keys(
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
) -> list[str]:
    """Sorted credential parameter names the user must supply: `{placeholder}`
    references in `auth_template` values not pre-filled by
    `organization_credentials`."""
    return sorted(
        placeholders_in_template(auth_template) - organization_credentials.keys()
    )


def is_user_authenticated_for_app(
    app: ExternalApp,
    user_cred: ExternalAppUserCredential | None,
) -> bool:
    """True iff the user has supplied every credential parameter the app's
    ``auth_template`` requires that the org hasn't pre-filled. Apps with no
    user-required keys need no credential row."""
    required = required_user_credential_keys(
        app.auth_template, app.organization_credentials.get_value(apply_mask=False)
    )
    if not required:
        return True
    if user_cred is None:
        return False
    stored = user_cred.user_credentials.get_value(apply_mask=False)
    return all(k in stored for k in required)


@dataclass(frozen=True)
class SkillExternalAppDependencyState:
    external_app_id: int
    name: str
    enabled: bool
    ready: bool


def waits_for_app(dependency: SkillExternalAppDependencyState | None) -> bool:
    """The skill needs an app that is not ready for the user. Such a skill does
    not load, does not count for the skill limits and cannot be turned on. The
    only check of this rule: the run time, the limits and the toggle call it."""
    return dependency is not None and not dependency.ready


def app_dependency_states(
    user_ids: Iterable[UUID],
    db_session: Session,
    skill_ids: Iterable[UUID] | None = None,
) -> dict[tuple[UUID, UUID], SkillExternalAppDependencyState]:
    """The app each skill needs (all, or ``skill_ids``), for each user, keyed
    by (user id, skill id). Ready: the app is enabled and the user connected
    it. One query; skills with no app are left out."""
    users = set(user_ids)
    if not users:
        return {}
    stmt = (
        select(ExternalApp__Skill.skill_id, ExternalApp, ExternalAppUserCredential)
        .join(ExternalApp, ExternalApp.id == ExternalApp__Skill.external_app_id)
        .outerjoin(
            ExternalAppUserCredential,
            and_(
                ExternalAppUserCredential.external_app_id == ExternalApp.id,
                ExternalAppUserCredential.user_id.in_(users),
            ),
        )
        # Credentials written earlier in this session must be read as stored.
        .execution_options(populate_existing=True)
    )
    if skill_ids is not None:
        ids = set(skill_ids)
        if not ids:
            return {}
        stmt = stmt.where(ExternalApp__Skill.skill_id.in_(ids))
    apps: dict[UUID, ExternalApp] = {}
    credentials: dict[tuple[UUID, int], ExternalAppUserCredential] = {}
    for skill_id, app, credential in db_session.execute(stmt).all():
        apps[skill_id] = app
        if credential is not None:
            credentials[(credential.user_id, app.id)] = credential
    return {
        (user_id, skill_id): SkillExternalAppDependencyState(
            external_app_id=app.id,
            name=app.name,
            enabled=app.enabled,
            ready=app.enabled
            and is_user_authenticated_for_app(app, credentials.get((user_id, app.id))),
        )
        for skill_id, app in apps.items()
        for user_id in users
    }
