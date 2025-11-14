from uuid import UUID
from sqlalchemy.orm import Session
from onyx.configs.constants import NotificationType
from onyx.db.models import Persona__User
from onyx.db.models import Persona__UserGroup
from onyx.db.notification import create_notification
from onyx.server.features.persona.models import PersonaSharedNotificationData


def _remove_existing_associations(session: Session, persona_id: int) -> None:
    """Удаляет текущие связи персоны с пользователями и группами."""
    user_query = session.query(Persona__User).filter(
        Persona__User.persona_id == persona_id
    )
    user_query.delete(synchronize_session="fetch")

    group_query = session.query(Persona__UserGroup).filter(
        Persona__UserGroup.persona_id == persona_id
    )
    group_query.delete(synchronize_session="fetch")


def _notify_shared_persona(
    session: Session, persona_id: int, user_uuid: UUID
) -> None:
    """Создает уведомление о шере персоны для пользователя."""
    create_notification(
        user_id=user_uuid,
        notif_type=NotificationType.PERSONA_SHARED,
        db_session=session,
        additional_data=PersonaSharedNotificationData(
            persona_id=persona_id,
        ).model_dump(),
    )


def make_persona_private(
    persona_id: int,
    user_ids: list[UUID] | None,
    group_ids: list[int] | None,
    db_session: Session,
) -> None:
    """
    Делает персону приватной, удаляя старые связи и добавляя новые.
    Все изменения батчатся в одном коммите; входные данные дедуплицируются
    для предотвращения ошибок уникальности.
    """
    target_id = persona_id
    session = db_session

    _remove_existing_associations(session, target_id)

    user_assocs = []
    if user_ids:
        unique_users = set(user_ids)
        idx = 0
        unique_list = list(unique_users)
        while idx < len(unique_list):
            uid = unique_list[idx]
            user_assocs.append(Persona__User(persona_id=target_id, user_id=uid))
            _notify_shared_persona(session, target_id, uid)
            idx += 1

    group_assocs = []
    if group_ids:
        unique_groups = set(group_ids)
        idx = 0
        unique_group_list = list(unique_groups)
        while idx < len(unique_group_list):
            gid = unique_group_list[idx]
            group_assocs.append(
                Persona__UserGroup(persona_id=target_id, user_group_id=gid)
            )
            idx += 1

    if user_assocs:
        session.add_all(user_assocs)
    if group_assocs:
        session.add_all(group_assocs)

    session.commit()
