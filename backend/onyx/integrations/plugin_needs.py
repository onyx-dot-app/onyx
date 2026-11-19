"""What the MCP servers a plugin needs are for one user. A need matches an
integration by URL at read time. A plugin never gives access to an
integration: each match shows the user's own state of that integration."""

from collections.abc import Iterable, Sequence
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationKind
from onyx.db.models import User
from onyx.db.plugin import get_versions_needs
from onyx.integrations.access import set_integration_enabled__no_commit
from onyx.integrations.connection_models import ConnectionState
from onyx.integrations.service import list_member_integrations
from onyx.server.features.integrations.models import MemberIntegration
from onyx.skills.models import PluginNeed
from onyx.utils.url import normalize_mcp_server_url


class PluginNeedState(str, Enum):
    """What one need is for one user. The first five are the values of
    ``MemberIntegrationState``: the state of the one integration it
    matches."""

    ON = "on"
    TURN_ON = "turn_on"
    SIGN_IN = "sign_in"
    NO_ACCESS = "no_access"
    TURNED_OFF = "turned_off"
    # No integration that the user's integration list shows matches.
    NOT_ADDED = "not_added"
    MORE_THAN_ONE = "more_than_one"
    # A local server, or a URL Onyx cannot match.
    NOT_SUPPORTED = "not_supported"


class PluginNeedView(PluginNeed):
    model_config = ConfigDict(frozen=True)

    state: PluginNeedState
    # The integration it matches; None unless exactly one matches.
    integration_id: int | None


class NeedCounts(BaseModel):
    """ "3 of 4 integrations available": supported needs that are on, and
    supported needs."""

    model_config = ConfigDict(frozen=True)

    available_count: int
    needed_count: int


def need_views(
    needs: Iterable[PluginNeed], integrations: Sequence[MemberIntegration]
) -> list[PluginNeedView]:
    """The state of each need, matched against the integrations the user's
    integration list shows (``list_member_integrations``). Each MCP
    integration matches by ``normalize_mcp_server_url`` of its server URL."""
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
                **need.model_dump(),
                state=state,
                integration_id=(
                    matches[0].id if need.supported and len(matches) == 1 else None
                ),
            )
        )
    return views


def need_counts(views: Iterable[PluginNeedView]) -> NeedCounts:
    supported = [view for view in views if view.supported]
    return NeedCounts(
        available_count=sum(view.state is PluginNeedState.ON for view in supported),
        needed_count=len(supported),
    )


def needs_of_versions(
    user: User, version_ids: Iterable[UUID], db_session: Session
) -> dict[UUID, list[PluginNeedView]]:
    """The need views of each version that has needs, for the user. Reads
    the user's integrations only when a version has a need."""
    needs = {
        version_id: version_needs
        for version_id, version_needs in get_versions_needs(
            version_ids, db_session
        ).items()
        if version_needs
    }
    if not needs:
        return {}
    integrations = list_member_integrations(user, db_session)
    return {
        version_id: need_views(version_needs, integrations)
        for version_id, version_needs in needs.items()
    }


def turn_on_needed_integrations__no_commit(
    user: User, needs: Sequence[PluginNeed], db_session: Session
) -> bool:
    """Turn on each needed integration that is off for the user and works
    when on: the user has access and a working connection, or the
    integration needs no sign-in. Returns whether one was turned on."""
    if not needs:
        return False
    integrations = list_member_integrations(user, db_session)
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
    """The names of the needs, of the given versions, that are not on for the
    user, sorted."""
    return sorted(
        {
            view.name
            for views in needs_of_versions(user, version_ids, db_session).values()
            for view in views
            if view.state is not PluginNeedState.ON
        }
    )
