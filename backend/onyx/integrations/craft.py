"""The integrations that Craft uses for a user and for the tasks of the user."""

import ipaddress
import re
from collections.abc import Collection, Sequence
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, InstanceOf
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType, IntegrationKind
from onyx.db.integration import (
    get_external_app_for_integration,
    list_enabled_integrations_by_id,
    list_integration_actions,
    list_integration_plugin_rows,
)
from onyx.db.integration_access import (
    get_plugin_ids_of_accessible_integrations,
    load_user_integration_states,
)
from onyx.db.integration_policy import (
    get_plugin_names,
    list_integration_holders,
    list_plugin_integrations,
    list_task_plugin_links,
    replace_task_plugin_links__no_commit,
)
from onyx.db.models import (
    ExternalApp,
    Integration,
    IntegrationAction,
    ScheduledTask__Plugin,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import WHOLE_DOMAIN_ACTION_TYPE
from onyx.integrations.connection_models import ConnectionState
from onyx.integrations.connections import integration_status
from onyx.integrations.models import (
    ActionSettings,
    ApprovalMode,
    EffectivePolicy,
    UsableIntegrationIds,
)
from onyx.integrations.policy import (
    parse_action_settings,
    resolve_action_policies,
)
from onyx.server.features.build.models import (
    TaskActionView,
    TaskIntegrationView,
    TaskPluginView,
)
from onyx.tools.models import PluginLinkConfiguration


def _enabled(holdings: Sequence[tuple[UUID, Integration]]) -> list[Integration]:
    integrations: dict[int, Integration] = {}
    for _, integration in holdings:
        if integration.enabled:
            integrations[integration.id] = integration
    return list(integrations.values())


def list_runnable_integrations(db_session: Session, user_id: UUID) -> list[Integration]:
    """The integrations that are on for the user, in integration order."""
    return list_enabled_integrations_by_id(
        db_session,
        [
            state.integration_id
            for state in load_user_integration_states([user_id], db_session)
            if state.on
        ],
    )


class TaskPlugins(BaseModel):
    """The plugin links of a task, with the integrations of each plugin that
    the owner still has access to, also one the owner turned off."""

    model_config = ConfigDict(frozen=True)

    links: list[InstanceOf[ScheduledTask__Plugin]]
    holdings: list[tuple[UUID, InstanceOf[Integration]]]

    def integrations(self) -> list[Integration]:
        """The enabled integrations, in integration order."""
        return _enabled(self.holdings)

    def link_settings(self, integration_id: int) -> list[ActionSettings]:
        """The settings of each plugin that holds the integration."""
        holders = {
            plugin_id
            for plugin_id, integration in self.holdings
            if integration.id == integration_id
        }
        return [
            parse_action_settings(link.action_settings)
            for link in self.links
            if link.plugin_id in holders
        ]


def load_task_plugins(db_session: Session, task_id: UUID, user_id: UUID) -> TaskPlugins:
    links = list_task_plugin_links(db_session, task_id)
    holdings = list_plugin_integrations(db_session, [link.plugin_id for link in links])
    accessible = {
        state.integration_id
        for state in load_user_integration_states(
            [user_id], db_session, {integration.id for _, integration in holdings}
        )
    }
    return TaskPlugins(
        links=links,
        holdings=[
            (plugin_id, integration)
            for plugin_id, integration in holdings
            if integration.id in accessible
        ],
    )


def load_usable_integration_ids(
    db_session: Session, user_id: UUID
) -> UsableIntegrationIds:
    states = [
        state
        for state in load_user_integration_states([user_id], db_session)
        if state.integration_enabled
    ]
    accessible = frozenset(state.integration_id for state in states)
    by_plugin: dict[UUID, set[int]] = {}
    for plugin_id, integration in list_integration_holders(db_session, accessible):
        by_plugin.setdefault(plugin_id, set()).add(integration.id)
    return UsableIntegrationIds(
        on=frozenset(state.integration_id for state in states if state.on),
        accessible=accessible,
        accessible_by_plugin={
            plugin_id: frozenset(ids) for plugin_id, ids in by_plugin.items()
        },
    )


def list_connectable_apps(db_session: Session, user: User) -> list[ExternalApp]:
    """The external apps of the integrations the user runs that the user can
    still connect: Not connected or Needs reconnect. The agent offers to
    connect them."""
    apps: list[ExternalApp] = []
    for integration in list_runnable_integrations(db_session, user.id):
        if integration.kind is not IntegrationKind.API:
            continue
        app = get_external_app_for_integration(integration.id, db_session)
        if app is None:
            continue
        state = integration_status(integration, user, db_session).state
        if state in (ConnectionState.NOT_CONNECTED, ConnectionState.NEEDS_RECONNECT):
            apps.append(app)
    return apps


def task_link_settings(
    db_session: Session, task_id: UUID, user_id: UUID, integration_id: int
) -> list[ActionSettings]:
    return load_task_plugins(db_session, task_id, user_id).link_settings(integration_id)


def _interactive_policies(
    db_session: Session,
    integration: Integration,
    actions: Sequence[IntegrationAction],
    action_keys: Collection[str],
    user_id: UUID | None,
    link_settings: Sequence[ActionSettings | None],
) -> dict[str, EffectivePolicy]:
    return resolve_action_policies(
        db_session,
        integration=integration,
        actions=actions,
        action_keys=action_keys,
        user_id=user_id,
        link_settings=link_settings,
        approval_mode=ApprovalMode.INTERACTIVE,
        chat_session_id=None,
    )


def resolve_craft_action_policies(
    db_session: Session,
    *,
    integration: Integration,
    actions: Sequence[IntegrationAction],
    action_keys: Collection[str],
    user_id: UUID,
    task: TaskPlugins | None,
) -> dict[str, EffectivePolicy]:
    """``actions`` are the stored actions of the integration. A scheduled run
    uses the settings of its task, not the saved Always allow choices of its
    owner, and blocks each action of an integration that no plugin of the
    task holds."""
    if task is None:
        return _interactive_policies(
            db_session, integration, actions, action_keys, user_id, [None]
        )
    return _interactive_policies(
        db_session,
        integration,
        actions,
        action_keys,
        None,
        task.link_settings(integration.id),
    )


def always_asks(kind: IntegrationKind, action_key: str) -> bool:
    """The sandbox proxy asks for each request that matches no action of an
    API integration, whatever the policy is, unless the policy is Blocked."""
    return kind is IntegrationKind.API and action_key == WHOLE_DOMAIN_ACTION_TYPE


def _shown_policy(
    integration: Integration, action_key: str, policy: EffectivePolicy
) -> EffectivePolicy:
    if (
        always_asks(integration.kind, action_key)
        and policy is not EffectivePolicy.BLOCKED
    ):
        return EffectivePolicy.ASK
    return policy


def _integration_view(
    db_session: Session,
    integration: Integration,
    actions: Sequence[IntegrationAction],
    user: User,
) -> TaskIntegrationView:
    # A scheduled run ignores the owner's Always allow choices.
    inherited = _interactive_policies(
        db_session,
        integration,
        actions,
        [action.key for action in actions],
        None,
        [None],
    )
    app = (
        get_external_app_for_integration(integration.id, db_session)
        if integration.kind is IntegrationKind.API
        else None
    )
    return TaskIntegrationView(
        id=integration.id,
        name=integration.name,
        kind=integration.kind,
        app_type=app.app_type if app is not None else None,
        status=integration_status(integration, user, db_session),
        actions=[
            TaskActionView(
                key=action.key,
                display_name=action.display_name,
                description=action.description,
                integration_policy=_shown_policy(
                    integration, action.key, inherited[action.key]
                ),
                locked=inherited[action.key] is EffectivePolicy.BLOCKED
                or not integration.users_can_save_always_allow
                or always_asks(integration.kind, action.key),
            )
            for action in actions
        ],
    )


def _known_actions(settings: ActionSettings, keys: set[str]) -> ActionSettings:
    return settings.model_copy(
        update={
            "actions": {
                key: value for key, value in settings.actions.items() if key in keys
            }
        }
    )


def list_task_plugin_views(
    db_session: Session, user: User, task_id: UUID | None
) -> list[TaskPluginView]:
    """Each plugin that names an integration, other than OpenAPI, that is on
    for the user, and each plugin of the task that holds an integration the
    user has access to, also one that is off, so that a save keeps its
    settings. ``task_id`` None gives the catalog for a new task: no plugin is
    enabled and each action inherits. The stored settings leave out action
    keys that no integration of the plugin has any more, so a save does not
    send them back."""
    links = (
        {
            link.plugin_id: parse_action_settings(link.action_settings)
            for link in list_task_plugin_links(db_session, task_id)
        }
        if task_id is not None
        else {}
    )
    states = {
        state.integration_id: state
        for state in load_user_integration_states([user.id], db_session)
    }
    plugins_of_on_integrations = {
        row.plugin_id
        for rows in list_integration_plugin_rows(
            [integration_id for integration_id, state in states.items() if state.on],
            db_session,
        ).values()
        for row in rows
    }
    integrations_by_plugin: dict[UUID, list[Integration]] = {}
    action_keys: dict[UUID, set[str]] = {}
    actions: dict[int, list[IntegrationAction]] = {}
    for plugin_id, integration in list_plugin_integrations(
        db_session, plugins_of_on_integrations | set(links)
    ):
        state = states.get(integration.id)
        if state is None or (plugin_id not in links and not state.on):
            continue
        if integration.id not in actions:
            actions[integration.id] = list_integration_actions(
                integration.id, db_session
            )
        if plugin_id in links:
            integrations_by_plugin.setdefault(plugin_id, [])
            action_keys.setdefault(plugin_id, set()).update(
                action.key for action in actions[integration.id]
            )
        if integration.enabled and integration.tool_id is None:
            integrations_by_plugin.setdefault(plugin_id, []).append(integration)
    names = get_plugin_names(db_session, list(integrations_by_plugin))
    views = [
        TaskPluginView(
            plugin_id=plugin_id,
            plugin_name=names.get(plugin_id, ""),
            enabled=plugin_id in links,
            action_settings=(
                _known_actions(links[plugin_id], action_keys.get(plugin_id, set()))
                if plugin_id in links
                else None
            ),
            integrations=[
                _integration_view(
                    db_session, integration, actions[integration.id], user
                )
                for integration in integrations
            ],
        )
        for plugin_id, integrations in integrations_by_plugin.items()
    ]
    return sorted(views, key=lambda view: (view.plugin_name.lower(), view.plugin_id))


def replace_task_plugins__no_commit(
    db_session: Session,
    user: User,
    task_id: UUID,
    plugins: list[PluginLinkConfiguration],
) -> None:
    """Save the plugins of a task with their action settings. Each plugin must
    hold an integration that the owner has access to, and each action key
    must be an action of one of its integrations."""
    ids = [plugin.plugin_id for plugin in plugins]
    if len(set(ids)) != len(ids):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "A plugin can appear only once")
    if set(ids) - get_plugin_ids_of_accessible_integrations(user.id, db_session, ids):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Plugin not found")
    keys: dict[UUID, set[str]] = {plugin_id: set() for plugin_id in ids}
    for plugin_id, integration in list_plugin_integrations(db_session, ids):
        keys[plugin_id].update(
            action.key
            for action in list_integration_actions(integration.id, db_session)
        )
    for plugin in plugins:
        if plugin.action_settings.actions.keys() - keys[plugin.plugin_id]:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Unknown plugin action")
    replace_task_plugin_links__no_commit(
        db_session,
        task_id,
        {
            plugin.plugin_id: plugin.action_settings.model_dump(mode="json")
            for plugin in plugins
        },
    )


def craft_service_urls(app: ExternalApp) -> list[str]:
    """The origins of the URL patterns of an app that Craft can show as links."""
    service_urls: list[str] = []
    for pattern in app.upstream_url_patterns:
        if app.app_type != ExternalAppType.CUSTOM:
            pattern = pattern.removeprefix("^")
        authority = pattern.partition("://")[2].split("/", 1)[0].rsplit("@", 1)[-1]
        if app.app_type != ExternalAppType.CUSTOM:
            if "?" in authority or re.search(r"(?<!\\)\.", authority):
                continue
            pattern = pattern.replace(r"\.", ".").replace(r"\-", "-")
        host_port, separator, query = authority.partition("?")
        if separator and "=" not in query:
            continue
        if re.search(r"[\s*+|(){}^$]", host_port):
            continue
        try:
            parsed = urlsplit(pattern)
            hostname = parsed.hostname
            port = parsed.port
            if parsed.scheme not in ("http", "https") or not hostname:
                continue
            if ":" in hostname:
                hostname = f"[{ipaddress.IPv6Address(hostname).compressed}]"
            elif not re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*",
                hostname,
            ):
                continue
        except ValueError:
            continue
        origin = f"{parsed.scheme}://{hostname}"
        if port is not None and port != {"http": 80, "https": 443}[parsed.scheme]:
            origin += f":{port}"
        if origin not in service_urls:
            service_urls.append(origin)

    return service_urls
