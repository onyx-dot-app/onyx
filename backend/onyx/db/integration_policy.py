from collections.abc import Collection, Sequence
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from onyx.db.enums import ApprovalDecidedVia, IntegrationActionPolicyValue
from onyx.db.models import (
    ApprovalRequest,
    ChatSession,
    Integration,
    IntegrationActionPolicy,
    Persona__Plugin,
    Plugin,
    Plugin__Integration,
    ScheduledTask__Plugin,
    Tool,
)
from onyx.db.plugin_access import visible_plugin_ids
from onyx.integrations.models import (
    ActionSettings,
    LinkValue,
    PersonaPluginLink,
    PersonaPluginSnapshot,
    PolicyRows,
)


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


def list_task_plugin_links(
    db_session: Session, task_id: UUID
) -> list[ScheduledTask__Plugin]:
    return list(
        db_session.scalars(
            select(ScheduledTask__Plugin)
            .where(ScheduledTask__Plugin.scheduled_task_id == task_id)
            .order_by(ScheduledTask__Plugin.plugin_id)
        ).all()
    )


def replace_task_plugin_links__no_commit(
    db_session: Session, task_id: UUID, links: dict[UUID, dict[str, object]]
) -> None:
    """Replace the plugins of a task, each with its raw ``action_settings``."""
    db_session.execute(
        delete(ScheduledTask__Plugin).where(
            ScheduledTask__Plugin.scheduled_task_id == task_id
        )
    )
    db_session.add_all(
        ScheduledTask__Plugin(
            scheduled_task_id=task_id, plugin_id=plugin_id, action_settings=settings
        )
        for plugin_id, settings in links.items()
    )
    db_session.flush()


def get_plugin_names(
    db_session: Session, plugin_ids: Collection[UUID]
) -> dict[UUID, str]:
    if not plugin_ids:
        return {}
    # .all(): a Result has keys(), so dict() would read it as a mapping.
    return dict(
        db_session.execute(
            select(Plugin.id, Plugin.name).where(Plugin.id.in_(plugin_ids))
        )
        .tuples()
        .all()
    )


def plugin_ids_for_integrations(
    integration_ids: Collection[int], user_id: UUID | None, db_session: Session
) -> dict[int, UUID]:
    """One plugin for each integration: the first one the user can see, else
    the first one, by plugin id."""
    if not integration_ids:
        return {}
    visible = (
        set(db_session.scalars(visible_plugin_ids(user_id)).all())
        if user_id is not None
        else set()
    )
    chosen: dict[int, UUID] = {}
    for integration_id, plugin_id in db_session.execute(
        select(Plugin__Integration.integration_id, Plugin__Integration.plugin_id)
        .where(Plugin__Integration.integration_id.in_(integration_ids))
        .order_by(Plugin__Integration.integration_id, Plugin__Integration.plugin_id)
    ).tuples():
        current = chosen.get(integration_id)
        if current is None or (plugin_id in visible and current not in visible):
            chosen[integration_id] = plugin_id
    return chosen


def legacy_tool_plugin_links(
    tools: Sequence[Tool], user_id: UUID | None, db_session: Session
) -> list[PersonaPluginLink]:
    """The plugin links for old tool ids of an agent request. A custom tool
    gives the plugin of its integration with no settings. MCP tools give the
    plugin of their server, with each other action blocked, as the migration
    does. A tool with no integration gives nothing."""
    mcp_tool_names: dict[int, list[str]] = {}
    for tool in tools:
        if tool.mcp_server_id is not None:
            mcp_tool_names.setdefault(tool.mcp_server_id, []).append(tool.name)
    custom_tool_ids = [tool.id for tool in tools if tool.openapi_schema is not None]
    custom_integration_ids: set[int] = set()
    server_integrations: dict[int, int] = {}
    if custom_tool_ids or mcp_tool_names:
        for integration_id, tool_id, server_id in db_session.execute(
            select(
                Integration.id, Integration.tool_id, Integration.mcp_server_id
            ).where(
                or_(
                    Integration.tool_id.in_(custom_tool_ids),
                    Integration.mcp_server_id.in_(mcp_tool_names),
                )
            )
        ).tuples():
            if tool_id is not None:
                custom_integration_ids.add(integration_id)
            if server_id is not None:
                server_integrations[server_id] = integration_id
    plugins = plugin_ids_for_integrations(
        custom_integration_ids | set(server_integrations.values()),
        user_id,
        db_session,
    )
    links: dict[UUID, PersonaPluginLink] = {}
    for integration_id in sorted(custom_integration_ids):
        plugin_id = plugins.get(integration_id)
        if plugin_id is not None:
            links.setdefault(plugin_id, PersonaPluginLink(plugin_id=plugin_id))
    for server_id, names in sorted(mcp_tool_names.items()):
        server_integration_id = server_integrations.get(server_id)
        if server_integration_id is None:
            continue
        plugin_id = plugins.get(server_integration_id)
        if plugin_id is None or plugin_id in links:
            continue
        links[plugin_id] = PersonaPluginLink(
            plugin_id=plugin_id,
            action_settings=ActionSettings(
                default=LinkValue.BLOCKED,
                actions=dict.fromkeys(sorted(names), LinkValue.INHERIT),
            ),
        )
    return list(links.values())


def write_persona_plugin_links__no_commit(
    persona_id: int,
    links: Sequence[PersonaPluginLink],
    *,
    replace: bool,
    db_session: Session,
) -> None:
    """Write the plugin links of an agent. ``replace`` deletes the links that
    are not in ``links`` and rewrites the settings; otherwise a link that
    exists stays as it is."""
    existing = {
        link.plugin_id: link
        for link in list_persona_plugin_links(db_session, persona_id)
    }
    wanted = {link.plugin_id: link for link in links}
    if replace:
        for plugin_id, row in existing.items():
            if plugin_id not in wanted:
                db_session.delete(row)
    for plugin_id, link in wanted.items():
        settings = link.action_settings.model_dump(mode="json", exclude_defaults=True)
        row = existing.get(plugin_id)
        if row is None:
            db_session.add(
                Persona__Plugin(
                    persona_id=persona_id,
                    plugin_id=plugin_id,
                    action_settings=settings,
                )
            )
        elif replace and row.action_settings != settings:
            row.action_settings = settings
    db_session.flush()


def list_persona_plugin_snapshots(
    persona_id: int, db_session: Session
) -> list[PersonaPluginSnapshot]:
    return [
        PersonaPluginSnapshot(
            plugin_id=plugin_id,
            plugin_name=name,
            action_settings=ActionSettings.model_validate(settings or {}),
        )
        for plugin_id, name, settings in db_session.execute(
            select(
                Persona__Plugin.plugin_id, Plugin.name, Persona__Plugin.action_settings
            )
            .join(Plugin, Plugin.id == Persona__Plugin.plugin_id)
            .where(Persona__Plugin.persona_id == persona_id)
            .order_by(Plugin.name, Plugin.id)
        ).tuples()
    ]
