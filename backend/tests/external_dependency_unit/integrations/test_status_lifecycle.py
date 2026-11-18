"""integration_status and the connection lifecycle."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration_connection import (
    delete_connection__no_commit,
    get_connection,
    get_oauth_client,
    mark_connection_needs_reconnect__no_commit,
)
from onyx.db.models import IntegrationConnection
from onyx.db.user_preferences import deactivate_user
from onyx.integrations.connection_models import (
    SIGN_IN_SETTINGS_CHANGED_REASON,
    ConnectionSecret,
    ConnectionState,
)
from onyx.integrations.connections import (
    integration_status,
    mark_sign_in_settings_changed,
    sign_in_settings_for,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import make_app_integration
from tests.external_dependency_unit.integrations.conftest import (
    add_connection,
    new_oauth_client,
)


def test_status_four_states(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    individual, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    shared, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    user = make_test_user("status")

    status = integration_status(individual, user, db_session)
    assert status.state is ConnectionState.NOT_CONNECTED

    status = integration_status(shared, user, db_session)
    assert status.state is ConnectionState.NOT_SET_UP
    assert status.reason == (
        f"{shared.name} is not set up for your organization. Ask your admin."
    )

    connection = add_connection(
        db_session, individual, user.id, ConnectionSecret(fields={"api_key": "k"})
    )
    assert (
        integration_status(individual, user, db_session).state
        is ConnectionState.CONNECTED
    )

    mark_connection_needs_reconnect__no_commit(db_session, connection, "Key expired")
    db_session.commit()
    status = integration_status(individual, user, db_session)
    assert status.state is ConnectionState.NEEDS_RECONNECT
    assert status.reason == "Key expired"

    none_mode, _ = make_app_integration(
        db_session, auth_mode=IntegrationAuthMode.NONE, auth_method=None
    )
    assert (
        integration_status(none_mode, None, db_session).state
        is ConnectionState.CONNECTED
    )


def test_oauth_without_client_id_is_not_set_up(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    user = make_test_user("no_client")
    manual, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(IntegrationOAuthProviderMode.MANUAL),
    )
    assert integration_status(manual, user, db_session).state is (
        ConnectionState.NOT_SET_UP
    )
    # Discovery registers a client at the first sign-in.
    discovery, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(IntegrationOAuthProviderMode.DISCOVERY),
    )
    assert integration_status(discovery, user, db_session).state is (
        ConnectionState.NOT_CONNECTED
    )


def test_client_id_change_resets_connections_but_secret_change_does_not(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.MANUAL,
            client_id="client-1",
            client_secret="secret-1",
        ),
    )
    for prefix in ("settings_a", "settings_b"):
        user = make_test_user(prefix)
        add_connection(
            db_session, integration, user.id, ConnectionSecret(access_token="t")
        )
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None

    def apply_edit(client_id: str, client_secret: str) -> None:
        before = sign_in_settings_for(integration, oauth_client, None)
        oauth_client.client_id = client_id  # ty: ignore[invalid-assignment]
        oauth_client.client_secret = client_secret  # ty: ignore[invalid-assignment]
        integration.name = integration.name + " renamed"
        after = sign_in_settings_for(integration, oauth_client, None)
        if before != after:
            mark_sign_in_settings_changed(integration.id, db_session)
        db_session.commit()

    apply_edit("client-1", "secret-2")
    connections = db_session.scalars(
        select(IntegrationConnection).where(
            IntegrationConnection.integration_id == integration.id
        )
    ).all()
    assert {c.status for c in connections} == {IntegrationConnectionStatus.CONNECTED}

    apply_edit("client-2", "secret-2")
    assert len(connections) == 2
    for connection in connections:
        db_session.refresh(connection)
        assert connection.status is IntegrationConnectionStatus.NEEDS_RECONNECT
        assert connection.status_reason == SIGN_IN_SETTINGS_CHANGED_REASON
    assert (
        integration_status(integration, user, db_session).state
        is ConnectionState.NEEDS_RECONNECT
    )


def test_disconnect_deletes_only_the_user_row(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    user = make_test_user("disconnect")
    other = make_test_user("disconnect_other")
    add_connection(
        db_session, integration, user.id, ConnectionSecret(fields={"a": "1"})
    )
    add_connection(
        db_session, integration, other.id, ConnectionSecret(fields={"a": "2"})
    )

    assert delete_connection__no_commit(db_session, integration.id, user.id) is True
    assert get_connection(db_session, integration.id, user.id) is None
    assert get_connection(db_session, integration.id, other.id) is not None
    assert delete_connection__no_commit(db_session, integration.id, user.id) is False


def test_deactivation_deletes_connections(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    user = make_test_user("deactivate")
    add_connection(
        db_session, integration, user.id, ConnectionSecret(fields={"a": "1"})
    )

    deactivate_user(user, db_session)

    assert get_connection(db_session, integration.id, user.id) is None
