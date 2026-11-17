"""The integrations that Craft uses for a user: each enabled integration that a
plugin the user runs holds. A scheduled run uses only the integrations of the
plugins of its task, with the action settings of the task."""

from collections.abc import Collection
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType, IntegrationKind
from onyx.db.integration import (
    get_external_app_for_integration,
    list_integration_actions,
)
from onyx.db.integration_policy import (
    get_plugin_names,
    list_plugin_integrations,
    list_task_plugin_links,
    replace_task_plugin_links__no_commit,
)
from onyx.db.models import ExternalApp, Integration, User
from onyx.db.plugin_access import load_user_plugin_states
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.connection_models import ConnectionState
from onyx.integrations.connections import IntegrationStatus, integration_status
from onyx.integrations.models import (
    ActionSettings,
    ApprovalMode,
    EffectivePolicy,
    LinkValue,
)
from onyx.integrations.policy import (
    parse_action_settings,
    resolve_action_policies,
)
from onyx.tools.models import PluginLinkConfiguration


def _enabled_integrations(
    db_session: Session, plugin_ids: Collection[UUID]
) -> list[Integration]:
    integrations: dict[int, Integration] = {}
    for _, integration in list_plugin_integrations(db_session, plugin_ids):
        if integration.enabled:
            integrations[integration.id] = integration
    return list(integrations.values())


def list_runnable_integrations(db_session: Session, user_id: UUID) -> list[Integration]:
    """The enabled integrations of the plugins that the user can see and has
    turned on, in integration order."""
    return _enabled_integrations(
        db_session,
        [
            state.plugin_id
            for state in load_user_plugin_states([user_id], db_session)
            if state.enabled
        ],
    )


def list_visible_integrations(db_session: Session, user_id: UUID) -> list[Integration]:
    """The enabled integrations of the plugins that the user can see, on or
    off."""
    return _enabled_integrations(
        db_session,
        [state.plugin_id for state in load_user_plugin_states([user_id], db_session)],
    )


def _visible_task_plugin_ids(
    db_session: Session, task_id: UUID, user_id: UUID
) -> set[UUID]:
    """The plugins of the task that the owner can still see. The task attached
    them on purpose, so the owner's on/off choice does not apply."""
    links = list_task_plugin_links(db_session, task_id)
    return {
        state.plugin_id
        for state in load_user_plugin_states(
            [user_id], db_session, [link.plugin_id for link in links]
        )
    }


def list_scheduled_run_integrations(
    db_session: Session, task_id: UUID, user_id: UUID
) -> list[Integration]:
    """The integrations a scheduled run can match: those the owner runs (the
    gate blocks each one that no task plugin holds) and those of the task
    plugins the owner can see."""
    integrations = {
        integration.id: integration
        for integration in list_runnable_integrations(db_session, user_id)
    }
    for integration in _enabled_integrations(
        db_session, _visible_task_plugin_ids(db_session, task_id, user_id)
    ):
        integrations.setdefault(integration.id, integration)
    return sorted(integrations.values(), key=lambda integration: integration.id)


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
    """The settings of each plugin of the task that holds the integration and
    that the task owner can still see."""
    links = list_task_plugin_links(db_session, task_id)
    visible = _visible_task_plugin_ids(db_session, task_id, user_id)
    holders = {
        plugin_id
        for plugin_id, integration in list_plugin_integrations(db_session, visible)
        if integration.id == integration_id
    }
    return [
        parse_action_settings(link.action_settings)
        for link in links
        if link.plugin_id in holders
    ]


def resolve_craft_action_policies(
    db_session: Session,
    *,
    integration: Integration,
    action_keys: Collection[str],
    user_id: UUID,
    task_id: UUID | None,
) -> dict[str, EffectivePolicy]:
    """The policy of each action for a Craft session. An interactive session
    has no link settings. A scheduled run uses the settings of its task, and
    blocks each action of an integration that no plugin of the task holds.
    Both keep the approval wait of the proxy for Ask."""
    if task_id is None:
        return resolve_action_policies(
            db_session,
            integration=integration,
            action_keys=action_keys,
            user_id=user_id,
            link_settings=[],
            approval_mode=ApprovalMode.INTERACTIVE,
            chat_session_id=None,
        )
    settings = task_link_settings(db_session, task_id, user_id, integration.id)
    if not settings:
        return dict.fromkeys(action_keys, EffectivePolicy.BLOCKED)
    return resolve_action_policies(
        db_session,
        integration=integration,
        action_keys=action_keys,
        user_id=user_id,
        link_settings=settings,
        approval_mode=ApprovalMode.INTERACTIVE,
        chat_session_id=None,
    )


class TaskActionView(BaseModel):
    key: str
    display_name: str
    description: str | None
    # The setting of the task; Inherit uses the integration setting.
    value: LinkValue
    # What a run does with the setting of the task.
    effective_policy: EffectivePolicy
    # What a run does with Inherit.
    integration_policy: EffectivePolicy


class TaskIntegrationView(BaseModel):
    id: int
    name: str
    kind: IntegrationKind
    app_type: ExternalAppType | None
    status: IntegrationStatus
    actions: list[TaskActionView]


class TaskPluginView(BaseModel):
    plugin_id: UUID
    plugin_name: str
    # The task uses the plugin.
    enabled: bool
    # The stored settings of the task for the plugin; None when not enabled.
    action_settings: ActionSettings | None
    integrations: list[TaskIntegrationView]


def _policies(
    db_session: Session,
    integration: Integration,
    keys: list[str],
    user_id: UUID,
    link: ActionSettings | None,
) -> dict[str, EffectivePolicy]:
    return resolve_action_policies(
        db_session,
        integration=integration,
        action_keys=keys,
        user_id=user_id,
        link_settings=[link],
        approval_mode=ApprovalMode.INTERACTIVE,
        chat_session_id=None,
    )


def _integration_view(
    db_session: Session, integration: Integration, user: User, link: ActionSettings
) -> TaskIntegrationView:
    actions = list_integration_actions(integration.id, db_session)
    keys = [action.key for action in actions]
    with_link = _policies(db_session, integration, keys, user.id, link)
    inherited = _policies(db_session, integration, keys, user.id, None)
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
                value=link.value_for(action.key),
                effective_policy=with_link[action.key],
                integration_policy=inherited[action.key],
            )
            for action in actions
        ],
    )


def list_task_plugin_views(
    db_session: Session, user: User, task_id: UUID | None
) -> list[TaskPluginView]:
    """Each plugin that the user runs and that holds an enabled integration,
    and each visible plugin of the task. ``task_id`` None gives the catalog
    for a new task: no plugin is enabled and each action inherits."""
    links = (
        {
            link.plugin_id: parse_action_settings(link.action_settings)
            for link in list_task_plugin_links(db_session, task_id)
        }
        if task_id is not None
        else {}
    )
    plugin_ids = [
        state.plugin_id
        for state in load_user_plugin_states([user.id], db_session)
        if state.enabled or state.plugin_id in links
    ]
    integrations_by_plugin: dict[UUID, list[Integration]] = {}
    for plugin_id, integration in list_plugin_integrations(db_session, plugin_ids):
        if integration.enabled:
            integrations_by_plugin.setdefault(plugin_id, []).append(integration)
    names = get_plugin_names(db_session, list(integrations_by_plugin))
    views = [
        TaskPluginView(
            plugin_id=plugin_id,
            plugin_name=names.get(plugin_id, ""),
            enabled=plugin_id in links,
            action_settings=links.get(plugin_id),
            integrations=[
                _integration_view(
                    db_session,
                    integration,
                    user,
                    links.get(plugin_id, ActionSettings()),
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
    be visible to the owner, and each action key must be an action of one of
    its integrations."""
    ids = [plugin.plugin_id for plugin in plugins]
    if len(set(ids)) != len(ids):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "A plugin can appear only once")
    visible = {
        state.plugin_id for state in load_user_plugin_states([user.id], db_session, ids)
    }
    if set(ids) - visible:
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
