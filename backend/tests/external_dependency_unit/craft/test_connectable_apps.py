from __future__ import annotations

from collections.abc import Generator
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    PluginInstallationPolicy,
)
from onyx.db.integration_access import set_integration_preferences__no_commit
from onyx.db.models import (
    Integration,
    Integration__User,
)
from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.craft import list_connectable_apps, list_runnable_integrations
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_connectable_apps_list,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_app_integration,
    turn_off_integrations,
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


def test_lists_the_apps_that_are_on_and_need_a_connection(
    db_session: Session, created: list[int], make_test_user: MakeTestUser
) -> None:
    user = make_test_user("connectable")
    needs_setup = _app(db_session, created, "needs-setup")
    connected = _app(db_session, created, "already-connected")
    no_sign_in = _app(db_session, created, "no-sign-in", IntegrationAuthMode.NONE)
    turned_off = _app(db_session, created, "turned-off")
    give_access(
        db_session,
        [needs_setup, connected, no_sign_in],
        published=True,
        installation_policy=PluginInstallationPolicy.DEFAULT,
    )
    give_access(
        db_session,
        [turned_off],
        published=True,
        installation_policy=PluginInstallationPolicy.DEFAULT,
    )
    turn_off_integrations(db_session, user.id, [turned_off])
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


def test_a_share_makes_an_integration_runnable_when_the_user_turns_it_on(
    db_session: Session,
    make_test_user: MakeTestUser,
    created: list[int],
) -> None:
    """Craft runs a private integration for a user with a share who turned
    it on."""
    owner = make_test_user("runnable_owner")
    shared = make_test_user("runnable_shared")
    private = _app(db_session, created, "shared-app", IntegrationAuthMode.NONE)
    give_access(db_session, [private], published=False, owner_user_id=owner.id)
    db_session.add(Integration__User(integration_id=private.id, user_id=shared.id))
    db_session.commit()

    def runnable(user_id: UUID) -> list[int]:
        return [
            integration.id
            for integration in list_runnable_integrations(db_session, user_id)
            if integration.id == private.id
        ]

    assert runnable(shared.id) == []

    set_integration_preferences__no_commit(shared.id, [private.id], True, db_session)
    db_session.commit()

    assert runnable(shared.id) == [private.id]
