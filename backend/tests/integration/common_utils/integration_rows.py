"""Integration rows for integration tests, written to the stack's database.

An MCP server made through the admin MCP routes has no integration, and chat
offers no action of it. These helpers make the integration of such a server,
its actions, agent links and policy rows."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import delete, select

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    IntegrationActionPolicyValue,
)
from onyx.db.models import (
    Integration,
    IntegrationActionPolicy,
    Persona__Integration,
)


def link_persona(
    persona_id: int, integration_id: int, action_settings: Mapping[str, object]
) -> None:
    """Set the agent's link to the integration, as the agent editor saves it."""
    with get_session_with_current_tenant() as db_session:
        link = db_session.scalar(
            select(Persona__Integration).where(
                Persona__Integration.persona_id == persona_id,
                Persona__Integration.integration_id == integration_id,
            )
        )
        if link is None:
            db_session.add(
                Persona__Integration(
                    persona_id=persona_id,
                    integration_id=integration_id,
                    action_settings=dict(action_settings),
                )
            )
        else:
            link.action_settings = dict(action_settings)
        db_session.commit()


def only_actions(actions: Sequence[str]) -> dict[str, object]:
    """The settings the migration writes for an agent with these MCP tools:
    each other action is blocked."""
    return {"default": "blocked", "actions": dict.fromkeys(actions, "inherit")}


def set_admin_policies(
    integration_id: int,
    policies: Mapping[str, IntegrationActionPolicyValue] | None = None,
    *,
    users_can_save_always_allow: bool | None = None,
) -> None:
    """Replace the admin rows of these actions, as the admin Actions tab
    saves them."""
    with get_session_with_current_tenant() as db_session:
        for action, policy in (policies or {}).items():
            db_session.execute(
                delete(IntegrationActionPolicy).where(
                    IntegrationActionPolicy.integration_id == integration_id,
                    IntegrationActionPolicy.action == action,
                    IntegrationActionPolicy.user_id.is_(None),
                )
            )
            db_session.add(
                IntegrationActionPolicy(
                    integration_id=integration_id, action=action, policy=policy
                )
            )
        if users_can_save_always_allow is not None:
            db_session.get_one(
                Integration, integration_id
            ).users_can_save_always_allow = users_can_save_always_allow
        db_session.commit()


def save_always_allow(integration_id: int, user_id: UUID, action: str) -> None:
    """The user's saved Always allow for one action."""
    with get_session_with_current_tenant() as db_session:
        db_session.add(
            IntegrationActionPolicy(
                integration_id=integration_id,
                action=action,
                user_id=user_id,
                policy=IntegrationActionPolicyValue.ALLOW,
            )
        )
        db_session.commit()
