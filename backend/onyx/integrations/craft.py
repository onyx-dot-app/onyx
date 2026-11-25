"""The integrations that Craft uses for a user and for the tasks of the user."""

import ipaddress
import re
from collections.abc import Collection, Sequence
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType, IntegrationKind
from onyx.db.integration import (
    get_external_app_for_integration,
    list_enabled_integrations_by_id,
    list_external_apps_by_integration,
    list_integrations_by_ids,
)
from onyx.db.integration_access import load_user_integration_states
from onyx.db.integration_policy import (
    list_task_integration_links,
    replace_task_integration_links__no_commit,
)
from onyx.db.models import ExternalApp, Integration, IntegrationAction, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.actions import integration_actions
from onyx.integrations.connection_models import ConnectionState
from onyx.integrations.connections import integration_status
from onyx.integrations.models import (
    ActionSettings,
    ApprovalMode,
    EffectivePolicy,
    UsableIntegrationIds,
)
from onyx.integrations.policy import (
    always_asks,
    parse_action_settings,
    resolve_action_policies,
)
from onyx.server.features.build.models import TaskActionView, TaskIntegrationView
from onyx.tools.models import IntegrationLinkConfiguration


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


def load_usable_integration_ids(
    db_session: Session, user_id: UUID
) -> UsableIntegrationIds:
    states = [
        state
        for state in load_user_integration_states([user_id], db_session)
        if state.integration_enabled
    ]
    return UsableIntegrationIds(
        on=frozenset(state.integration_id for state in states if state.on),
        accessible=frozenset(state.integration_id for state in states),
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


def _interactive_policies(
    db_session: Session,
    integration: Integration,
    actions: Sequence[IntegrationAction],
    action_keys: Collection[str],
    user_id: UUID | None,
    link_settings: ActionSettings | None,
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
) -> dict[str, EffectivePolicy]:
    """The policies of a Craft session: ``actions`` are the stored actions
    of the integration, and the saved Always allow choices of ``user_id``
    apply."""
    return _interactive_policies(
        db_session, integration, actions, action_keys, user_id, ActionSettings()
    )


def _integration_view(
    db_session: Session,
    integration: Integration,
    actions: Sequence[IntegrationAction],
    user: User,
    settings: ActionSettings | None,
    app: ExternalApp | None,
) -> TaskIntegrationView:
    # A scheduled run ignores the owner's Always allow choices.
    inherited = _interactive_policies(
        db_session,
        integration,
        actions,
        [action.key for action in actions],
        None,
        ActionSettings(),
    )
    return TaskIntegrationView(
        id=integration.id,
        name=integration.name,
        kind=integration.kind,
        app_type=app.app_type if app is not None else None,
        status=integration_status(integration, user, db_session),
        enabled=settings is not None,
        action_settings=(
            _known_actions(settings, {action.key for action in actions})
            if settings is not None
            else None
        ),
        runnable=_chat_runnable(integration, app),
        actions=[
            TaskActionView(
                key=action.key,
                display_name=action.display_name,
                description=action.description,
                integration_policy=inherited[action.key],
                locked=inherited[action.key] is EffectivePolicy.BLOCKED
                or not integration.users_can_save_always_allow
                or always_asks(integration.kind, action.key),
            )
            for action in actions
        ],
    )


def _chat_runnable(integration: Integration, app: ExternalApp | None) -> bool:
    """Chat runs an API integration through its ``api_app`` or its preset
    (``build_integration_chat_tools``)."""
    return integration.enabled and not (
        integration.kind is IntegrationKind.API
        and integration.api_app_id is None
        and (app is None or app.app_type == ExternalAppType.CUSTOM)
    )


def _known_actions(settings: ActionSettings, keys: set[str]) -> ActionSettings:
    return settings.model_copy(
        update={
            "actions": {
                key: value for key, value in settings.actions.items() if key in keys
            }
        }
    )


def list_task_integration_views(
    db_session: Session, user: User, task_id: UUID | None
) -> list[TaskIntegrationView]:
    """Each integration that is on for the user and that chat can run, and
    each integration of the task that the user has access to, also one that
    is off or that chat cannot run, so that a save keeps its settings.
    ``task_id`` None gives the catalog for a new task: no integration is
    enabled and each action inherits. The stored settings leave out action
    keys that the integration has no more, so a save does not send them
    back."""
    links = (
        {
            link.integration_id: parse_action_settings(link.action_settings)
            for link in list_task_integration_links(db_session, task_id)
        }
        if task_id is not None
        else {}
    )
    states = {
        state.integration_id: state
        for state in load_user_integration_states([user.id], db_session)
    }
    apps = list_external_apps_by_integration(list(states), db_session)
    views = [
        _integration_view(
            db_session,
            integration,
            integration_actions(integration.id, db_session),
            user,
            links.get(integration.id),
            apps.get(integration.id),
        )
        for integration in list_integrations_by_ids(list(states), db_session)
        if integration.id in links
        or (
            states[integration.id].on
            and _chat_runnable(integration, apps.get(integration.id))
        )
    ]
    return sorted(views, key=lambda view: (view.name.lower(), view.id))


def replace_task_integrations__no_commit(
    db_session: Session,
    user: User,
    task_id: UUID,
    integrations: list[IntegrationLinkConfiguration],
) -> None:
    """Save the integrations of a task with their action settings. The owner
    must have access to each integration, and each action key must be an
    action of its integration. A stored link that the owner lost access to
    is not in the catalog, so the editor cannot send it: it stays, and the
    run blocks it until the access comes back."""
    ids = [link.integration_id for link in integrations]
    if len(set(ids)) != len(ids):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "An integration can appear only once"
        )
    accessible = {
        state.integration_id
        for state in load_user_integration_states([user.id], db_session, ids)
    }
    if set(ids) - accessible:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Integration not found")
    for link in integrations:
        keys = {
            action.key
            for action in integration_actions(link.integration_id, db_session)
        }
        if link.action_settings.actions.keys() - keys:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Unknown integration action")
    stored = {
        link.integration_id: link.action_settings
        for link in list_task_integration_links(db_session, task_id)
    }
    still_accessible = {
        state.integration_id
        for state in load_user_integration_states([user.id], db_session, stored)
    }
    kept = {
        integration_id: settings
        for integration_id, settings in stored.items()
        if integration_id not in still_accessible
    }
    replace_task_integration_links__no_commit(
        db_session,
        task_id,
        kept
        | {
            link.integration_id: link.action_settings.model_dump(mode="json")
            for link in integrations
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
