"""Whether a user has connected the external app that a skill needs.

Below ``onyx.db.plugin`` in the import order, so the skill limit check can use
it."""

import re
from collections.abc import Iterable
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


def app_skill_ids(skill_ids: Iterable[UUID], db_session: Session) -> set[UUID]:
    """The skills among ``skill_ids`` that need an external app."""
    ids = set(skill_ids)
    if not ids:
        return set()
    return set(
        db_session.scalars(
            select(ExternalApp__Skill.skill_id).where(
                ExternalApp__Skill.skill_id.in_(ids)
            )
        )
    )


def ready_app_skill_pairs(
    pairs: Iterable[tuple[UUID, UUID]], db_session: Session
) -> set[tuple[UUID, UUID]]:
    """The (user id, skill id) pairs whose skill's app is enabled and connected
    for that user, in one query."""
    wanted = set(pairs)
    if not wanted:
        return set()
    user_ids = {user_id for user_id, _ in wanted}
    skill_ids = {skill_id for _, skill_id in wanted}
    rows = db_session.execute(
        select(ExternalApp__Skill.skill_id, ExternalApp, ExternalAppUserCredential)
        .join(ExternalApp, ExternalApp.id == ExternalApp__Skill.external_app_id)
        .outerjoin(
            ExternalAppUserCredential,
            and_(
                ExternalAppUserCredential.external_app_id == ExternalApp.id,
                ExternalAppUserCredential.user_id.in_(user_ids),
            ),
        )
        .where(ExternalApp__Skill.skill_id.in_(skill_ids))
        # Credentials written earlier in this session must be read as stored.
        .execution_options(populate_existing=True)
    ).all()
    apps: dict[UUID, ExternalApp] = {}
    credentials: dict[tuple[UUID, int], ExternalAppUserCredential] = {}
    for skill_id, app, credential in rows:
        apps[skill_id] = app
        if credential is not None:
            credentials[(credential.user_id, app.id)] = credential
    return {
        (user_id, skill_id)
        for user_id, skill_id in wanted
        if skill_id in apps
        and apps[skill_id].enabled
        and is_user_authenticated_for_app(
            apps[skill_id], credentials.get((user_id, apps[skill_id].id))
        )
    }
