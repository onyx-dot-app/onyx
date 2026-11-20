"""A plugin never gives access to an integration: each match shows the user's own state of that integration."""

from collections.abc import Iterable, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationKind
from onyx.db.integration import list_mcp_servers_by_integration
from onyx.db.models import User
from onyx.db.plugin import get_versions_needs
from onyx.integrations.access import set_integration_enabled__no_commit
from onyx.integrations.connection_models import ConnectionState
from onyx.integrations.models import NeedCounts, PluginNeedState, PluginNeedView
from onyx.integrations.service import list_member_integrations
from onyx.server.features.integrations.models import MemberIntegration
from onyx.skills.models import PluginNeed
from onyx.utils.url import normalize_mcp_server_url


def need_views(
    needs: Iterable[PluginNeed], integrations: Sequence[MemberIntegration]
) -> list[PluginNeedView]:
    by_url: dict[str, list[MemberIntegration]] = {}
    for integration in integrations:
        if integration.kind is not IntegrationKind.MCP or not integration.server_url:
            continue
        key = normalize_mcp_server_url(integration.server_url)
        if key is not None:
            by_url.setdefault(key, []).append(integration)

    views: list[PluginNeedView] = []
    for need in needs:
        matches = by_url.get(need.url, []) if need.url is not None else []
        if not need.supported:
            state = PluginNeedState.NOT_SUPPORTED
        elif not matches:
            state = PluginNeedState.NOT_ADDED
        elif len(matches) > 1:
            state = PluginNeedState.MORE_THAN_ONE
        else:
            state = PluginNeedState(matches[0].access.state.value)
        views.append(
            PluginNeedView(
                **need.model_dump(exclude={"supported"}),
                state=state,
                integration_id=(
                    matches[0].id if need.supported and len(matches) == 1 else None
                ),
            )
        )
    return views


def integrations_for_needs(user: User, db_session: Session) -> list[MemberIntegration]:
    """The member integrations, with the server URL of each no-access MCP
    integration for matching only. Never return these rows to the user."""
    integrations = list_member_integrations(user, db_session)
    servers = list_mcp_servers_by_integration(
        [
            integration.id
            for integration in integrations
            if integration.kind is IntegrationKind.MCP
            and integration.server_url is None
        ],
        db_session,
    )
    return [
        (
            integration.model_copy(
                update={"server_url": servers[integration.id].server_url}
            )
            if integration.id in servers
            else integration
        )
        for integration in integrations
    ]


def need_counts(views: Iterable[PluginNeedView]) -> NeedCounts:
    supported = [view for view in views if view.supported]
    return NeedCounts(
        available_count=sum(view.state is PluginNeedState.ON for view in supported),
        needed_count=len(supported),
    )


def needs_of_versions(
    user: User, version_ids: Iterable[UUID], db_session: Session
) -> dict[UUID, list[PluginNeedView]]:
    needs = {
        version_id: version_needs
        for version_id, version_needs in get_versions_needs(
            version_ids, db_session
        ).items()
        if version_needs
    }
    if not needs:
        return {}
    integrations = integrations_for_needs(user, db_session)
    return {
        version_id: need_views(version_needs, integrations)
        for version_id, version_needs in needs.items()
    }


def turn_on_needed_integrations__no_commit(
    user: User, needs: Sequence[PluginNeed], db_session: Session
) -> bool:
    if not needs:
        return False
    integrations = integrations_for_needs(user, db_session)
    connected = {
        integration.id
        for integration in integrations
        if integration.status.state is ConnectionState.CONNECTED
    }
    turned_on = False
    for view in need_views(needs, integrations):
        if view.state is PluginNeedState.TURN_ON and view.integration_id in connected:
            set_integration_enabled__no_commit(
                user, view.integration_id, True, db_session
            )
            turned_on = True
    return turned_on


def unavailable_need_names(
    user: User, version_ids: Iterable[UUID], db_session: Session
) -> list[str]:
    return sorted(
        {
            view.name
            for views in needs_of_versions(user, version_ids, db_session).values()
            for view in views
            if view.state is not PluginNeedState.ON
        }
    )
