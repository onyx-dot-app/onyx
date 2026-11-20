from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ExternalAppType,
)
from onyx.db.models import (
    ExternalApp,
    Skill,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_external_app_by_id(
    db_session: Session,
    external_app_id: int,
) -> ExternalApp | None:
    return db_session.scalar(
        select(ExternalApp).where(ExternalApp.id == external_app_id)
    )


def get_built_in_external_app(
    db_session: Session,
    app_type: ExternalAppType,
) -> ExternalApp | None:
    """The tenant's built-in external app of the given type, or None.

    Callers expect at most one configured row for a built-in provider type.
    ``CUSTOM`` is rejected because multiple custom apps may share that type, so
    callers must identify them by ID instead.
    """
    if not app_type.is_built_in:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"get_built_in_external_app requires a built-in app type, got "
            f"'{app_type.value}'.",
        )
    stmt = select(ExternalApp).where(ExternalApp.app_type == app_type)
    return db_session.scalars(stmt).one_or_none()


def associate_built_in_skill__no_commit(
    db_session: Session,
    app: ExternalApp,
) -> Skill:
    """Create or reuse the provider's built-in skill row for a new app. No row
    links the skill to the app: a user gets the skill through a plugin that
    holds the app's integration (``onyx.db.app_skill``). Refuses a second app
    of one built-in type. Flush only; callers own the transaction.
    """
    from onyx.db.skill import add_new_skill__no_commit

    other_app_id = db_session.scalar(
        select(ExternalApp.id)
        .where(ExternalApp.app_type == app.app_type, ExternalApp.id != app.id)
        .limit(1)
    )
    if other_app_id is not None:
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            f"The built-in app '{app.app_type.value}' is already configured.",
        )

    built_in_skill_id = EXTERNAL_APP_BUILT_IN_SKILL_IDS.get(app.app_type)
    if built_in_skill_id is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Only built-in external apps have a system skill.",
        )

    skill = db_session.scalar(
        select(Skill).where(
            Skill.built_in_skill_id == built_in_skill_id,
            Skill.name == built_in_skill_id,
        )
    )
    if skill is None:
        skill = add_new_skill__no_commit(
            Skill(
                name=built_in_skill_id,
                description="",
                built_in_skill_id=built_in_skill_id,
            ),
            db_session,
        )
    return skill


def delete_external_app__no_commit(
    db_session: Session,
    external_app_id: int,
) -> None:
    """Delete an app and the built-in skill row of its preset. Skills of the
    app's plugins stay as they are. Flush only; the caller owns the
    transaction.
    """
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )

    built_in_skill_id = EXTERNAL_APP_BUILT_IN_SKILL_IDS.get(app.app_type)
    db_session.delete(app)
    if built_in_skill_id is not None:
        for skill in db_session.scalars(
            select(Skill).where(Skill.built_in_skill_id == built_in_skill_id)
        ):
            db_session.delete(skill)
    db_session.flush()
