from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    PluginInstallationPolicy,
)
from onyx.db.models import Integration, UserPluginPreference
from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.craft import list_connectable_apps
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_connectable_apps_list,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    hold_in_plugin,
    make_app_integration,
)
from tests.external_dependency_unit.integrations.conftest import add_connection


@pytest.fixture
def created(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[int], None, None]:
    integration_ids: list[int] = []
    try:
        yield integration_ids
    finally:
        delete_integrations(db_session, integration_ids)


def _app(
    db_session: Session,
    created: list[int],
    name: str,
    auth_mode: IntegrationAuthMode = IntegrationAuthMode.INDIVIDUAL,
) -> Integration:
    integration, _ = make_app_integration(
        db_session,
        app_type=ExternalAppType.CUSTOM,
        upstream_url_patterns=[f"https://{name}.example.com/*"],
        name=name,
        auth_mode=auth_mode,
        auth_method=(
            IntegrationAuthMethod.API_KEY
            if auth_mode is not IntegrationAuthMode.NONE
            else None
        ),
        header_template=(
            {"Authorization": "Bearer {api_key}"}
            if auth_mode is not IntegrationAuthMode.NONE
            else None
        ),
    )
    created.append(integration.id)
    return integration


def test_lists_the_apps_of_run_plugins_that_need_a_connection(
    db_session: Session, created: list[int], make_test_user: MakeTestUser
) -> None:
    user = make_test_user("connectable")
    needs_setup = _app(db_session, created, "needs-setup")
    connected = _app(db_session, created, "already-connected")
    no_sign_in = _app(db_session, created, "no-sign-in", IntegrationAuthMode.NONE)
    turned_off = _app(db_session, created, "turned-off")
    hold_in_plugin(
        db_session,
        [needs_setup, connected, no_sign_in],
        published=True,
        installation_policy=PluginInstallationPolicy.DEFAULT,
    )
    off_plugin = hold_in_plugin(
        db_session,
        [turned_off],
        published=True,
        installation_policy=PluginInstallationPolicy.DEFAULT,
    )
    db_session.add(
        UserPluginPreference(user_id=user.id, plugin_id=off_plugin.id, enabled=False)
    )
    db_session.commit()
    add_connection(
        db_session, connected, user.id, ConnectionSecret(fields={"api_key": "k"})
    )

    names = {app.name for app in list_connectable_apps(db_session, user)}

    assert "needs-setup" in names
    assert "already-connected" not in names
    assert "no-sign-in" not in names
    assert "turned-off" not in names

    apps_list = build_connectable_apps_list(list_connectable_apps(db_session, user))
    assert "**needs-setup**" in apps_list
    assert "turned-off" not in apps_list
