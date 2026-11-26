from collections.abc import Collection, Mapping, Sequence
from uuid import UUID

from sqlalchemy import delete, false, or_, select
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.enums import (
    ApprovalDecidedVia,
    IntegrationActionPolicyValue,
    ScheduledTaskRunStatus,
)
from onyx.db.models import (
    ApprovalRequest,
    ChatMessage,
    Integration,
    IntegrationActionPolicy,
    Persona__Integration,
    ScheduledTask__Integration,
    ScheduledTaskRun,
    Tool,
)
from onyx.integrations.models import (
    ActionSettings,
    LinkValue,
    PersonaIntegrationLink,
    PersonaIntegrationSnapshot,
    PolicyRows,
)


def get_policy_rows(
    db_session: Session, integration_id: int, user_id: UUID | None
) -> PolicyRows:
    """The admin rows, and the rows of ``user_id`` when given."""
    return list_policy_rows(db_session, [integration_id], user_id)[integration_id]


def list_admin_policy_rows(
    db_session: Session, integration_ids: Collection[int]
) -> dict[int, dict[str, IntegrationActionPolicyValue]]:
    """The admin rows of each integration, by action key."""
    rows: dict[int, dict[str, IntegrationActionPolicyValue]] = {
        integration_id: {} for integration_id in integration_ids
    }
    if not integration_ids:
        return rows
    for integration_id, action, policy in db_session.execute(
        select(
            IntegrationActionPolicy.integration_id,
            IntegrationActionPolicy.action,
            IntegrationActionPolicy.policy,
        ).where(
            IntegrationActionPolicy.integration_id.in_(integration_ids),
            IntegrationActionPolicy.user_id.is_(None),
        )
    ).tuples():
        rows[integration_id][action] = policy
    return rows


def list_policy_rows(
    db_session: Session, integration_ids: Collection[int], user_id: UUID | None
) -> dict[int, PolicyRows]:
    rows = {key: PolicyRows(admin={}, user={}) for key in integration_ids}
    if not integration_ids:
        return rows
    owner = IntegrationActionPolicy.user_id.is_(None)
    if user_id is not None:
        owner = or_(owner, IntegrationActionPolicy.user_id == user_id)
    for integration_id, row_user_id, action, policy in db_session.execute(
        select(
            IntegrationActionPolicy.integration_id,
            IntegrationActionPolicy.user_id,
            IntegrationActionPolicy.action,
            IntegrationActionPolicy.policy,
        ).where(IntegrationActionPolicy.integration_id.in_(integration_ids), owner)
    ).tuples():
        row = rows[integration_id]
        (row.admin if row_user_id is None else row.user)[action] = policy
    return rows


def list_session_granted_actions(
    db_session: Session,
    chat_session_id: UUID | None,
    integration_ids: Collection[int | None],
) -> dict[int | None, set[str]]:
    """The actions of each integration that "Approve for this chat" approved
    in the chat. The None key gives the grants with no integration: built-in
    actions' (`onyx:` keys) and deleted integrations' actions."""
    granted: dict[int | None, set[str]] = {key: set() for key in integration_ids}
    if chat_session_id is None or not integration_ids:
        return granted
    for integration_id, action in db_session.execute(
        select(ApprovalRequest.integration_id, ApprovalRequest.action_id).where(
            ApprovalRequest.chat_session_id == chat_session_id,
            or_(
                ApprovalRequest.integration_id.in_(
                    [key for key in integration_ids if key is not None]
                ),
                ApprovalRequest.integration_id.is_(None)
                if None in granted
                else false(),
            ),
            ApprovalRequest.decided_via == ApprovalDecidedVia.SESSION_GRANT,
        )
    ).tuples():
        granted[integration_id].add(action)
    return granted


def get_session_granted_actions(
    db_session: Session, chat_session_id: UUID, integration_id: int | None
) -> set[str]:
    """The actions of the integration that "Approve for this chat" approved
    in the chat."""
    return list_session_granted_actions(db_session, chat_session_id, [integration_id])[
        integration_id
    ]


def list_persona_integration_links(
    db_session: Session, persona_id: int
) -> list[Persona__Integration]:
    return list(
        db_session.scalars(
            select(Persona__Integration)
            .where(Persona__Integration.persona_id == persona_id)
            .order_by(Persona__Integration.integration_id)
        ).all()
    )


def list_task_integration_links(
    db_session: Session, task_id: UUID
) -> list[ScheduledTask__Integration]:
    return list(
        db_session.scalars(
            select(ScheduledTask__Integration)
            .where(ScheduledTask__Integration.scheduled_task_id == task_id)
            .order_by(ScheduledTask__Integration.integration_id)
        ).all()
    )


def list_in_flight_task_links(
    db_session: Session, chat_session_id: UUID
) -> list[ScheduledTask__Integration] | None:
    """The integration links of the task whose run is in flight in the chat.
    None: no run is in flight there, and the chat uses its agent. The run's
    response decides: the run status follows a resumed response only at the
    next dispatch tick."""
    task_id = db_session.scalar(
        select(ScheduledTaskRun.task_id).where(
            ScheduledTaskRun.chat_session_id == chat_session_id,
            ScheduledTaskRun.status.in_(
                (
                    ScheduledTaskRunStatus.RUNNING,
                    ScheduledTaskRunStatus.AWAITING_APPROVAL,
                )
            ),
        )
    )
    if task_id is None:
        return None
    # The run's response is the first response of its chat.
    response_status = db_session.scalar(
        select(ChatMessage.response_status)
        .where(
            ChatMessage.chat_session_id == chat_session_id,
            ChatMessage.message_type == MessageType.ASSISTANT,
            ChatMessage.response_status.is_not(None),
        )
        .order_by(ChatMessage.id)
        .limit(1)
    )
    if response_status is not None and response_status.is_terminal:
        return None
    return list_task_integration_links(db_session, task_id)


def replace_task_integration_links__no_commit(
    db_session: Session, task_id: UUID, links: Mapping[int, dict[str, object]]
) -> None:
    """Replace the integrations of a task, each with its raw
    ``action_settings``."""
    db_session.execute(
        delete(ScheduledTask__Integration).where(
            ScheduledTask__Integration.scheduled_task_id == task_id
        )
    )
    db_session.add_all(
        ScheduledTask__Integration(
            scheduled_task_id=task_id,
            integration_id=integration_id,
            action_settings=settings,
        )
        for integration_id, settings in links.items()
    )
    db_session.flush()


def legacy_tool_integration_links(
    tools: Sequence[Tool], db_session: Session
) -> list[PersonaIntegrationLink]:
    """The integration links for old tool ids of an agent request. A custom
    tool gives its integration with no settings. MCP tools give the
    integration of their server, with each other action blocked, as the
    migration does. A tool with no integration gives nothing."""
    mcp_tool_names: dict[int, set[str]] = {}
    for tool in tools:
        if tool.mcp_server_id is not None:
            mcp_tool_names.setdefault(tool.mcp_server_id, set()).add(tool.name)
    custom_tool_ids = [tool.id for tool in tools if tool.openapi_schema is not None]
    if not custom_tool_ids and not mcp_tool_names:
        return []
    links: list[PersonaIntegrationLink] = []
    for integration_id, tool_id, server_id in db_session.execute(
        select(Integration.id, Integration.tool_id, Integration.mcp_server_id)
        .where(
            or_(
                Integration.tool_id.in_(custom_tool_ids),
                Integration.mcp_server_id.in_(mcp_tool_names),
            )
        )
        .order_by(Integration.id)
    ).tuples():
        if tool_id is not None:
            links.append(PersonaIntegrationLink(integration_id=integration_id))
        elif server_id is not None:
            links.append(
                PersonaIntegrationLink(
                    integration_id=integration_id,
                    action_settings=ActionSettings(
                        default=LinkValue.BLOCKED,
                        actions=dict.fromkeys(
                            sorted(mcp_tool_names[server_id]), LinkValue.INHERIT
                        ),
                    ),
                )
            )
    return links


def list_persona_openapi_tools(
    persona_id: int, db_session: Session
) -> list[tuple[Tool, Integration]]:
    """The OpenAPI tool row of each integration of the agent, with the
    integration. These are the old custom tool ids of the agent."""
    return [
        (tool, integration)
        for tool, integration in db_session.execute(
            select(Tool, Integration)
            .join(Integration, Integration.tool_id == Tool.id)
            .join(
                Persona__Integration,
                Persona__Integration.integration_id == Integration.id,
            )
            .where(Persona__Integration.persona_id == persona_id)
            .order_by(Tool.id)
        ).tuples()
    ]


def list_persona_mcp_tools(
    persona_id: int, db_session: Session
) -> list[tuple[int, Tool, bool]]:
    """The old MCP tool rows of each MCP integration of the agent, with the
    integration id and whether the link selects the tool (does not block its
    action). The selected rows are the old MCP tool ids of the agent."""
    return [
        (
            integration_id,
            tool,
            ActionSettings.model_validate(settings or {}).value_for(tool.name)
            is not LinkValue.BLOCKED,
        )
        for integration_id, settings, tool in db_session.execute(
            select(
                Persona__Integration.integration_id,
                Persona__Integration.action_settings,
                Tool,
            )
            .join(Integration, Integration.id == Persona__Integration.integration_id)
            .join(Tool, Tool.mcp_server_id == Integration.mcp_server_id)
            .where(Persona__Integration.persona_id == persona_id)
            .order_by(Tool.id)
        ).tuples()
    ]


def write_persona_integration_links__no_commit(
    persona_id: int,
    links: Sequence[PersonaIntegrationLink],
    db_session: Session,
) -> None:
    """Make the integration links of an agent equal ``links``."""
    existing = {
        link.integration_id: link
        for link in list_persona_integration_links(db_session, persona_id)
    }
    wanted = {link.integration_id: link for link in links}
    for integration_id, row in existing.items():
        if integration_id not in wanted:
            db_session.delete(row)
    for integration_id, link in wanted.items():
        settings = link.action_settings.model_dump(mode="json", exclude_defaults=True)
        row = existing.get(integration_id)
        if row is None:
            db_session.add(
                Persona__Integration(
                    persona_id=persona_id,
                    integration_id=integration_id,
                    action_settings=settings,
                )
            )
        elif row.action_settings != settings:
            row.action_settings = settings
    db_session.flush()


def list_persona_integration_snapshots(
    persona_id: int, db_session: Session
) -> list[PersonaIntegrationSnapshot]:
    return [
        PersonaIntegrationSnapshot(
            integration_id=integration_id,
            integration_name=name,
            action_settings=ActionSettings.model_validate(settings or {}),
        )
        for integration_id, name, settings in db_session.execute(
            select(
                Persona__Integration.integration_id,
                Integration.name,
                Persona__Integration.action_settings,
            )
            .join(Integration, Integration.id == Persona__Integration.integration_id)
            .where(Persona__Integration.persona_id == persona_id)
            .order_by(Integration.name, Integration.id)
        ).tuples()
    ]
