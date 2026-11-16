"""Which built-in app skills each user gets.

A user gets the built-in skill of a preset when the user runs a plugin that
holds an enabled integration made from that preset: the integration's
``external_app`` row has an ``app_type`` in ``EXTERNAL_APP_BUILT_IN_SKILL_IDS``.
This module is the only place of that rule."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import ExternalApp, Integration, Plugin__Integration
from onyx.db.plugin_access import UserPluginState, load_user_plugin_states
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS


def built_in_app_skills_by_user(
    user_ids: Iterable[UUID],
    db_session: Session,
    states: Iterable[UserPluginState] | None = None,
) -> dict[UUID, dict[str, int]]:
    """For each user, the built-in skill id of each preset the user gets,
    mapped to the external app that renders it. "Runs" is a plugin the user
    can see and has enabled. Only an integration the admin turned on counts
    (``integration.enabled``). When the user runs more than one integration of
    one preset, the one with the lowest integration id renders the skill.
    ``states``: the users' plugin states, when the caller has them."""
    users = set(user_ids)
    if not users:
        return {}
    if states is None:
        states = load_user_plugin_states(users, db_session)
    running: dict[UUID, set[UUID]] = {}
    for state in states:
        if state.enabled and state.user_id in users:
            running.setdefault(state.plugin_id, set()).add(state.user_id)
    result: dict[UUID, dict[str, int]] = {user_id: {} for user_id in users}
    if not running:
        return result
    rows = db_session.execute(
        select(Plugin__Integration.plugin_id, ExternalApp.id, ExternalApp.app_type)
        .join(
            ExternalApp,
            ExternalApp.integration_id == Plugin__Integration.integration_id,
        )
        .join(Integration, Integration.id == Plugin__Integration.integration_id)
        .where(
            Integration.enabled.is_(True),
            Plugin__Integration.plugin_id.in_(list(running)),
            ExternalApp.app_type.in_(list(EXTERNAL_APP_BUILT_IN_SKILL_IDS)),
        )
        .order_by(Plugin__Integration.integration_id)
    )
    for plugin_id, external_app_id, app_type in rows:
        skill_id = EXTERNAL_APP_BUILT_IN_SKILL_IDS[app_type]
        for user_id in running[plugin_id]:
            result[user_id].setdefault(skill_id, external_app_id)
    return result


def built_in_app_skills_for_user(
    user_id: UUID,
    db_session: Session,
    states: Iterable[UserPluginState] | None = None,
) -> dict[str, int]:
    """``built_in_app_skills_by_user`` for one user."""
    return built_in_app_skills_by_user([user_id], db_session, states)[user_id]


def plugin_ids_holding_external_app(
    db_session: Session, external_app: ExternalApp
) -> list[UUID]:
    """The plugins that hold the integration of ``external_app``."""
    if external_app.integration_id is None:
        return []
    return list(
        db_session.scalars(
            select(Plugin__Integration.plugin_id).where(
                Plugin__Integration.integration_id == external_app.integration_id
            )
        )
    )
