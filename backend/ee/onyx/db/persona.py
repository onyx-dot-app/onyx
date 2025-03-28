from uuid import UUID

from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
from onyx.db.models import Persona__User
from onyx.db.models import Persona__UserGroup
from onyx.db.notification import create_notification
from onyx.db.users import add_belongs_user_if_not_exists
from onyx.server.features.persona.models import PersonaSharedNotificationData


def make_persona_private(
    persona_id: int,
    user_ids: list[UUID] | None,
    group_ids: list[int] | None,
    db_session: Session,
    new_user_emails: list[str] | None = None,
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

            create_notification(
                user_id=user_id,
                notif_type=NotificationType.PERSONA_SHARED,
                db_session=db_session,
                additional_data=PersonaSharedNotificationData(
                    persona_id=persona_id,
                ).model_dump(),
            )

    # Handle new user emails (create users that don't exist yet)
    if new_user_emails is not None and len(new_user_emails) > 0:
        for email in new_user_emails:
            # Create a new user with BELONGS_TO_GROUP role if not exists
            user = add_belongs_user_if_not_exists(db_session=db_session, email=email)

            # Add user to persona
            db_session.add(Persona__User(persona_id=persona_id, user_id=user.id))

            # Create notification
            create_notification(
                user_id=user.id,
                notif_type=NotificationType.PERSONA_SHARED,
                db_session=db_session,
                additional_data=PersonaSharedNotificationData(
                    persona_id=persona_id,
                ).model_dump(),
            )

        db_session.commit()

    if group_ids:
        group_ids_set = set(group_ids)
        for group_id in group_ids_set:
            db_session.add(
                Persona__UserGroup(persona_id=persona_id, user_group_id=group_id)
            )

    db_session.commit()
