"""Shared builders for the agent-sharing permission/transfer/lifecycle tests."""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.enums import PersonaSharePermission
from onyx.db.models import Persona
from onyx.db.models import Persona__User
from onyx.db.models import Persona__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup


def create_test_persona(
    db_session: Session,
    owner: User | None,
    is_public: bool = False,
    is_listed: bool = True,
    builtin_persona: bool = False,
    owner_group_id: int | None = None,
    public_permission: PersonaSharePermission = PersonaSharePermission.VIEWER,
) -> Persona:
    persona = Persona(
        name=f"agent-sharing-test-{uuid4().hex[:8]}",
        description="agent sharing test persona",
        user_id=owner.id if owner else None,
        owner_group_id=owner_group_id,
        is_public=is_public,
        public_permission=public_permission,
        system_prompt="",
        task_prompt="",
        datetime_aware=True,
        builtin_persona=builtin_persona,
        is_listed=is_listed,
    )
    db_session.add(persona)
    db_session.commit()
    db_session.refresh(persona)
    return persona


def share_persona_with_user(
    db_session: Session,
    persona: Persona,
    user: User,
    permission: PersonaSharePermission,
) -> None:
    db_session.add(
        Persona__User(persona_id=persona.id, user_id=user.id, permission=permission)
    )
    db_session.commit()


def create_test_user_group(
    db_session: Session,
    members: list[User],
    curators: list[User] | None = None,
) -> UserGroup:
    group = UserGroup(name=f"agent-sharing-group-{uuid4().hex[:8]}")
    db_session.add(group)
    db_session.flush()
    curator_ids = {user.id for user in (curators or [])}
    for member in members:
        db_session.add(
            User__UserGroup(
                user_group_id=group.id,
                user_id=member.id,
                is_curator=member.id in curator_ids,
            )
        )
    db_session.commit()
    db_session.refresh(group)
    return group


def share_persona_with_group(
    db_session: Session,
    persona: Persona,
    group: UserGroup,
    permission: PersonaSharePermission,
) -> None:
    db_session.add(
        Persona__UserGroup(
            persona_id=persona.id, user_group_id=group.id, permission=permission
        )
    )
    db_session.commit()
