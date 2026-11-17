from collections.abc import Collection
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from onyx.db.enums import ApprovalDecidedVia, IntegrationActionPolicyValue
from onyx.db.models import (
    ApprovalRequest,
    ChatSession,
    Integration,
    IntegrationActionPolicy,
    Persona__Plugin,
    Plugin__Integration,
)
from onyx.integrations.models import PolicyRows


def get_policy_rows(
    db_session: Session, integration_id: int, user_id: UUID | None
) -> PolicyRows:
    """The admin rows, and the rows of ``user_id`` when given."""
    owner = IntegrationActionPolicy.user_id.is_(None)
    if user_id is not None:
        owner = or_(owner, IntegrationActionPolicy.user_id == user_id)
    admin: dict[str, IntegrationActionPolicyValue] = {}
    user: dict[str, IntegrationActionPolicyValue] = {}
    for row_user_id, action, policy in db_session.execute(
        select(
            IntegrationActionPolicy.user_id,
            IntegrationActionPolicy.action,
            IntegrationActionPolicy.policy,
        ).where(IntegrationActionPolicy.integration_id == integration_id, owner)
    ).tuples():
        (admin if row_user_id is None else user)[action] = policy
    return PolicyRows(admin=admin, user=user)


def get_session_granted_actions(
    db_session: Session, chat_session_id: UUID, integration_id: int
) -> set[str]:
    """The actions of the integration that "Approve for this chat" approved
    in the chat."""
    return set(
        db_session.scalars(
            select(ApprovalRequest.action_id).where(
                ApprovalRequest.chat_session_id == chat_session_id,
                ApprovalRequest.integration_id == integration_id,
                ApprovalRequest.decided_via == ApprovalDecidedVia.SESSION_GRANT,
            )
        ).all()
    )


def list_persona_plugin_links(
    db_session: Session, persona_id: int
) -> list[Persona__Plugin]:
    return list(
        db_session.scalars(
            select(Persona__Plugin)
            .where(Persona__Plugin.persona_id == persona_id)
            .order_by(Persona__Plugin.plugin_id)
        ).all()
    )


def list_plugin_integrations(
    db_session: Session, plugin_ids: Collection[UUID]
) -> list[tuple[UUID, Integration]]:
    """Each integration that one of the plugins holds, with the plugin, in
    integration order."""
    if not plugin_ids:
        return []
    return [
        (plugin_id, integration)
        for plugin_id, integration in db_session.execute(
            select(Plugin__Integration.plugin_id, Integration)
            .join(Integration, Integration.id == Plugin__Integration.integration_id)
            .where(Plugin__Integration.plugin_id.in_(plugin_ids))
            .order_by(Integration.id, Plugin__Integration.plugin_id)
        ).tuples()
    ]


def get_chat_session_persona_id(
    db_session: Session, chat_session_id: UUID
) -> int | None:
    return db_session.scalar(
        select(ChatSession.persona_id).where(ChatSession.id == chat_session_id)
    )
