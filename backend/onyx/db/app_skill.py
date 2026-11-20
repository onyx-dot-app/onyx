from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.integration_access import load_user_integration_states
from onyx.db.models import ExternalApp, Integration
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS


def built_in_app_skills(user_id: UUID, db_session: Session) -> dict[str, int]:
    """The built-in skill id of each preset that the user gets, mapped to the
    external app that renders it. The user gets the skill of a preset when an
    integration of that preset is on for the user."""
    on = [
        state.integration_id
        for state in load_user_integration_states([user_id], db_session)
        if state.on
    ]
    if not on:
        return {}
    rows = db_session.execute(
        select(ExternalApp.id, ExternalApp.app_type)
        .join(Integration, Integration.external_app_id == ExternalApp.id)
        .where(
            Integration.id.in_(on),
            ExternalApp.app_type.in_(list(EXTERNAL_APP_BUILT_IN_SKILL_IDS)),
        )
    )
    return {
        EXTERNAL_APP_BUILT_IN_SKILL_IDS[app_type]: external_app_id
        for external_app_id, app_type in rows
    }
