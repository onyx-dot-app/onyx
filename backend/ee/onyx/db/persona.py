from uuid import UUID

from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
from onyx.db.models import Persona__User
from onyx.db.models import Persona__UserGroup
from onyx.db.notification import create_notification
from onyx.server.features.persona.models import PersonaSharedNotificationData


def make_persona_private(
    persona_id: int,
    creator_user_id: UUID | None,
    user_ids: list[UUID] | None,
    group_ids: list[int] | None,
    db_session: Session,
) -> None:
    """NOTE(rkuo): This function batches all updates into a single commit. If we don't
    dedupe the inputs, the commit will exception."""

    db_session.query(Persona__User).filter(
        Persona__User.persona_id == persona_id
    ).delete(synchronize_session="fetch")
    db_session.query(Persona__UserGroup).filter(
        Persona__UserGroup.persona_id == persona_id
    ).delete(synchronize_session="fetch")

    if user_ids:
        user_ids_set = set(user_ids)
        for user_id in user_ids_set:
            db_session.add(Persona__User(persona_id=persona_id, user_id=user_id))
            if user_id != creator_user_id:
                create_notification(
                    user_id=user_id,
                    notif_type=NotificationType.PERSONA_SHARED,
                    db_session=db_session,
                    additional_data=PersonaSharedNotificationData(
                        persona_id=persona_id,
                    ).model_dump(),
                )

    if group_ids:
        group_ids_set = set(group_ids)
        for group_id in group_ids_set:
            db_session.add(
                Persona__UserGroup(persona_id=persona_id, user_group_id=group_id)
            )

    db_session.commit()
