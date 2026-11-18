from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import ExternalApp, Integration, Plugin__Integration
from onyx.db.plugin_access import UserPluginState
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS


def built_in_app_skills(
    states: Iterable[UserPluginState], db_session: Session
) -> dict[str, int]:
    """The built-in skill id of each preset that one user gets, mapped to the
    external app that renders it. ``states`` are the user's plugin states. The
    user gets a preset's skill through a plugin the user can run that holds
    an enabled integration of that preset."""
    running = [state.plugin_id for state in states if state.can_run]
    if not running:
        return {}
    rows = db_session.execute(
        select(ExternalApp.id, ExternalApp.app_type)
        .join(Integration, Integration.external_app_id == ExternalApp.id)
        .join(
            Plugin__Integration,
            Plugin__Integration.integration_id == Integration.id,
        )
        .where(
            Integration.enabled.is_(True),
            Plugin__Integration.plugin_id.in_(running),
            ExternalApp.app_type.in_(list(EXTERNAL_APP_BUILT_IN_SKILL_IDS)),
        )
    )
    return {
        EXTERNAL_APP_BUILT_IN_SKILL_IDS[app_type]: external_app_id
        for external_app_id, app_type in rows
    }
