from collections.abc import Collection, Sequence
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from onyx.db.enums import ApprovalDecidedVia, IntegrationActionPolicyValue
from onyx.db.integration import (
    holds_only_integrations,
    list_integration_actions_by_id,
)
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
    db_session: Session, chat_session_id: UUID | None, integration_ids: Collection[int]
) -> dict[int, set[str]]:
    granted: dict[int, set[str]] = {key: set() for key in integration_ids}
    if chat_session_id is None or not integration_ids:
        return granted
    for integration_id, action in db_session.execute(
        select(ApprovalRequest.integration_id, ApprovalRequest.action_id).where(
            ApprovalRequest.chat_session_id == chat_session_id,
            ApprovalRequest.integration_id.in_(integration_ids),
            ApprovalRequest.decided_via == ApprovalDecidedVia.SESSION_GRANT,
        )
    ).tuples():
        if integration_id is not None:
            granted[integration_id].add(action)
    return granted


def get_session_granted_actions(
    db_session: Session, chat_session_id: UUID, integration_id: int
) -> set[str]:
    """The actions of the integration that "Approve for this chat" approved
    in the chat."""
    return list_session_granted_actions(db_session, chat_session_id, [integration_id])[
        integration_id
    ]


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


def list_integration_holders(
    db_session: Session, integration_ids: Collection[int]
) -> list[tuple[UUID, Integration]]:
    """Each plugin that holds one of the integrations, with the integration,
    in integration order."""
    if not integration_ids:
        return []
    return [
        (plugin_id, integration)
        for plugin_id, integration in db_session.execute(
            select(Plugin__Integration.plugin_id, Integration)
            .join(Integration, Integration.id == Plugin__Integration.integration_id)
            .where(Plugin__Integration.integration_id.in_(integration_ids))
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
    integration_ids: Collection[int],
    db_session: Session,
    attached: Collection[UUID] = (),
) -> dict[int, UUID]:
    """The plugin that names each integration on an agent: a plugin in
    ``attached``, else a plugin that holds only integrations, else any plugin
    that holds it."""
    if not integration_ids:
        return {}

    def rank(plugin_id: UUID, only_integrations: bool) -> int:
        if plugin_id in attached:
            return 0
        return 1 if only_integrations else 2

    chosen: dict[int, tuple[int, UUID]] = {}
    for integration_id, plugin_id, only_integrations in db_session.execute(
        select(
            Plugin__Integration.integration_id,
            Plugin__Integration.plugin_id,
            holds_only_integrations(),
        )
        .join(Plugin, Plugin.id == Plugin__Integration.plugin_id)
        .where(Plugin__Integration.integration_id.in_(integration_ids))
        .order_by(Plugin__Integration.integration_id, Plugin__Integration.plugin_id)
    ).tuples():
        candidate = (rank(plugin_id, only_integrations), plugin_id)
        current = chosen.get(integration_id)
        if current is None or candidate[0] < current[0]:
            chosen[integration_id] = candidate
    return {
        integration_id: plugin_id for integration_id, (_, plugin_id) in chosen.items()
    }


def legacy_tool_plugin_links(
    tools: Sequence[Tool],
    db_session: Session,
    attached: Collection[UUID] = (),
) -> list[PersonaPluginLink]:
    """The plugin links for old tool ids of an agent request. A custom tool
    gives the plugin of its integration with no settings. MCP tools give the
    plugin of their server, with each other action blocked, as the migration
    does. A tool with no integration gives nothing. A plugin in ``attached``
    wins for an integration that more than one plugin holds."""
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
        db_session,
        attached,
    )
    links: dict[UUID, PersonaPluginLink] = {}
    for integration_id in sorted(custom_integration_ids):
        plugin_id = plugins.get(integration_id)
        if plugin_id is not None:
            links.setdefault(plugin_id, PersonaPluginLink(plugin_id=plugin_id))
    mcp_names: dict[UUID, set[str]] = {}
    selected: dict[int, set[str]] = {}
    for server_id, names in sorted(mcp_tool_names.items()):
        server_integration_id = server_integrations.get(server_id)
        if server_integration_id is None:
            continue
        plugin_id = plugins.get(server_integration_id)
        if plugin_id is None or plugin_id in links:
            continue
        mcp_names.setdefault(plugin_id, set()).update(names)
        selected[server_integration_id] = set(names)
    # The settings of a plugin name actions, not servers: a name that another
    # server of the plugin has but was not selected on stays blocked.
    held = [
        (plugin_id, integration.id)
        for plugin_id, integration in list_plugin_integrations(
            db_session, list(mcp_names)
        )
        if integration.mcp_server_id is not None
    ]
    actions = list_integration_actions_by_id(
        [integration_id for _, integration_id in held], db_session
    )
    for plugin_id, integration_id in held:
        mcp_names[plugin_id] -= {
            action.key for action in actions[integration_id]
        } - selected.get(integration_id, set())
    for plugin_id, names in mcp_names.items():
        links[plugin_id] = PersonaPluginLink(
            plugin_id=plugin_id,
            action_settings=ActionSettings(
                default=LinkValue.BLOCKED,
                actions=dict.fromkeys(sorted(names), LinkValue.INHERIT),
            ),
        )
    return list(links.values())


def list_persona_openapi_tools(
    persona_id: int, db_session: Session
) -> list[tuple[UUID, Tool, Integration]]:
    """The OpenAPI tool row of each integration that a plugin of the agent
    holds, with the plugin and the integration. These are the old custom
    tool ids of the agent."""
    return [
        (plugin_id, tool, integration)
        for plugin_id, tool, integration in db_session.execute(
            select(Persona__Plugin.plugin_id, Tool, Integration)
            .join(
                Plugin__Integration,
                Plugin__Integration.plugin_id == Persona__Plugin.plugin_id,
            )
            .join(Integration, Integration.id == Plugin__Integration.integration_id)
            .join(Tool, Tool.id == Integration.tool_id)
            .where(Persona__Plugin.persona_id == persona_id)
            .order_by(Tool.id, Persona__Plugin.plugin_id)
        ).tuples()
    ]


def list_persona_mcp_tools(
    persona_id: int, db_session: Session
) -> list[tuple[UUID, Tool, bool]]:
    """The old MCP tool rows of each MCP integration that a plugin of the
    agent holds, with the plugin and whether the link selects the tool (does
    not block its action). The selected rows are the old MCP tool ids of the
    agent."""
    return [
        (
            plugin_id,
            tool,
            ActionSettings.model_validate(settings or {}).value_for(tool.name)
            is not LinkValue.BLOCKED,
        )
        for plugin_id, settings, tool in db_session.execute(
            select(Persona__Plugin.plugin_id, Persona__Plugin.action_settings, Tool)
            .join(
                Plugin__Integration,
                Plugin__Integration.plugin_id == Persona__Plugin.plugin_id,
            )
            .join(Integration, Integration.id == Plugin__Integration.integration_id)
            .join(Tool, Tool.mcp_server_id == Integration.mcp_server_id)
            .where(Persona__Plugin.persona_id == persona_id)
            .order_by(Tool.id, Persona__Plugin.plugin_id)
        ).tuples()
    ]


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
