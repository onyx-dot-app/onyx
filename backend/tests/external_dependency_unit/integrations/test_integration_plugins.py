"""Plugin writes on a plugin that holds an integration and no skill."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationAuthMode,
    IntegrationKind,
    PluginInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.integration_access import user_can_use_integration
from onyx.db.models import (
    Integration,
    Integration__User,
    MCPServer,
    Plugin,
    Plugin__Integration,
    Plugin__User,
    PluginVersion,
    User,
)
from onyx.db.plugin import (
    ORGANIZATION_LIBRARY_ID,
    PluginAccessChange,
    PluginUserGrant,
    apply_plugin_access_change__no_commit,
    get_or_create_user_uploads__no_commit,
    publish_plugin__no_commit,
)
from onyx.db.users import delete_user_from_db__no_commit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.craft.db_helpers import make_skill


def _private_integration_plugin(db_session: Session, owner: User) -> Plugin:
    """A private MCP integration in the owner's My uploads, held by a plugin
    with no skill, as the integration tables migration makes it."""
    server = MCPServer(
        owner=owner.email,
        name=f"plugins-{uuid4().hex[:8]}",
        server_url="https://example.com/mcp",
        is_public=False,
    )
    db_session.add(server)
    db_session.flush()
    plugin_id = uuid4()
    plugin = Plugin(
        id=plugin_id,
        name=server.name,
        description="",
        marketplace_id=get_or_create_user_uploads__no_commit(owner.id, db_session),
        author_user_id=owner.id,
        current_version_id=plugin_id,
    )
    db_session.add(plugin)
    db_session.flush()
    db_session.add(PluginVersion(id=plugin_id, plugin_id=plugin_id, version_number=1))
    integration = Integration(
        kind=IntegrationKind.MCP,
        name=server.name,
        auth_mode=IntegrationAuthMode.NONE,
        mcp_server_id=server.id,
        owner_user_id=owner.id,
    )
    db_session.add(integration)
    db_session.flush()
    db_session.add(
        Plugin__Integration(plugin_id=plugin_id, integration_id=integration.id)
    )
    db_session.flush()
    return plugin


def _skill(db_session: Session, name: str, author: User) -> UUID:
    return make_skill(db_session, name=name, author_user_id=author.id).id


@pytest.mark.usefixtures("tenant_context")
def test_share_and_publish_an_integration_plugin(db_session: Session) -> None:
    try:
        owner = create_test_user(db_session, "plugins_owner")
        other = create_test_user(db_session, "plugins_other")
        plugin = _private_integration_plugin(db_session, owner)

        apply_plugin_access_change__no_commit(
            [plugin.id],
            PluginAccessChange(
                user_grants=(
                    PluginUserGrant(
                        user_id=other.id, permission=SkillSharePermission.EDITOR
                    ),
                ),
                publish=True,
                on_name_clash="rename",
            ),
            None,
            db_session,
        ).raise_first_failure()

        db_session.refresh(plugin)
        assert plugin.marketplace_id == ORGANIZATION_LIBRARY_ID
        assert plugin.published_version_id == plugin.current_version_id
        assert (
            db_session.scalar(
                select(Plugin__User.permission).where(
                    Plugin__User.plugin_id == plugin.id,
                    Plugin__User.user_id == other.id,
                )
            )
            == SkillSharePermission.EDITOR
        )
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
def test_user_delete_keeps_private_integrations_for_their_people(
    db_session: Session,
) -> None:
    """A user delete leaves each private integration of the user private,
    with no owner and with its shares. The plugin that names it moves to the
    Organization library as Not available, so it stays. It does not block the
    delete as a private skill does."""
    try:
        owner = create_test_user(db_session, "plugins_owner")
        other = create_test_user(db_session, "plugins_other")
        plugin = _private_integration_plugin(db_session, owner)
        integration = db_session.scalars(
            select(Integration)
            .join(
                Plugin__Integration,
                Plugin__Integration.integration_id == Integration.id,
            )
            .where(Plugin__Integration.plugin_id == plugin.id)
        ).one()
        db_session.add(
            Integration__User(integration_id=integration.id, user_id=other.id)
        )
        db_session.flush()

        delete_user_from_db__no_commit(owner, db_session)

        db_session.refresh(plugin)
        assert plugin.marketplace_id == ORGANIZATION_LIBRARY_ID
        assert plugin.installation_policy == PluginInstallationPolicy.NOT_AVAILABLE
        assert plugin.published_version_id == plugin.current_version_id
        assert plugin.author_user_id is None
        db_session.refresh(integration)
        assert integration.owner_user_id is None
        assert integration.installation_policy == PluginInstallationPolicy.NOT_AVAILABLE
        assert user_can_use_integration(db_session, integration.id, other.id)
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
def test_publishing_a_skill_named_like_an_integration(db_session: Session) -> None:
    """A plugin that holds only integrations has no skill, so a skill with its
    name still publishes; only the plugin label takes a free name. A second
    skill with that name is refused."""
    try:
        owner = create_test_user(db_session, "plugins_owner")
        integration_plugin = _private_integration_plugin(db_session, owner)
        publish_plugin__no_commit(integration_plugin.id, "raise", db_session)
        name = integration_plugin.name

        first = _skill(db_session, name, owner)
        publish_plugin__no_commit(first, "raise", db_session)
        published = db_session.get(Plugin, first)
        assert published is not None
        assert published.marketplace_id == ORGANIZATION_LIBRARY_ID
        assert published.name == f"{name}-2"

        second = _skill(db_session, name, owner)
        with pytest.raises(OnyxError) as refused:
            publish_plugin__no_commit(second, "raise", db_session)
        assert refused.value.error_code == OnyxErrorCode.CONFLICT
    finally:
        db_session.rollback()
