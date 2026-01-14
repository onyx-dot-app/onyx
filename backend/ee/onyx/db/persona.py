from uuid import UUID

from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
from onyx.db.models import Persona
from onyx.db.models import Persona__User
from onyx.db.models import Persona__UserGroup
from onyx.db.notification import create_notification
from onyx.server.features.persona.models import PersonaSharedNotificationData


def update_persona_access(
    persona_id: int,
    creator_user_id: UUID | None,
    db_session: Session,
    is_public: bool | None = None,
    user_ids: list[UUID] | None = None,
    group_ids: list[int] | None = None,
) -> None:
    """Updates the access settings for a persona including public status, user shares,
    and group shares.

    NOTE: This function batches all updates. If we don't dedupe the inputs,
    the commit will exception.

    NOTE: Callers are responsible for committing."""

    if is_public is not None:
        persona = db_session.query(Persona).filter(Persona.id == persona_id).first()
        if persona:
            persona.is_public = is_public

    # NOTE: For user-ids and group-ids, `None` means "leave unchanged", `[]` means "clear all shares",
    # and a non-empty list means "replace with these shares".

    if user_ids is not None:
        db_session.query(Persona__User).filter(
            Persona__User.persona_id == persona_id
        ).delete(synchronize_session="fetch")

        user_ids_set = set(user_ids)
        for user_id in user_ids_set:
            db_session.add(Persona__User(persona_id=persona_id, user_id=user_id))
            if user_id != creator_user_id:
                create_notification(
                    user_id=user_id,
                    notif_type=NotificationType.PERSONA_SHARED,
                    title="A new agent was shared with you!",
                    db_session=db_session,
                    additional_data=PersonaSharedNotificationData(
                        persona_id=persona_id,
                    ).model_dump(),
                )

    if group_ids is not None:
        db_session.query(Persona__UserGroup).filter(
            Persona__UserGroup.persona_id == persona_id
        ).delete(synchronize_session="fetch")

        group_ids_set = set(group_ids)
        for group_id in group_ids_set:
            db_session.add(
                Persona__UserGroup(persona_id=persona_id, user_group_id=group_id)
            )
