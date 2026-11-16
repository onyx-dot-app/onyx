"""integration_status and the connection lifecycle."""

from collections.abc import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration_connection import (
    get_connection,
    get_oauth_client,
    list_connections_for_integration,
    mark_connection_needs_reconnect__no_commit,
)
from onyx.db.models import IntegrationConnection, User, User__UserGroup
from onyx.db.user_preferences import deactivate_user
from onyx.integrations.connection_models import (
    SIGN_IN_SETTINGS_CHANGED_REASON,
    ConnectionSecret,
    ConnectionState,
)
from onyx.integrations.connections import (
    disconnect,
    integration_status,
    mark_sign_in_settings_changed,
    sign_in_settings_changed,
    sign_in_settings_for,
)
from tests.external_dependency_unit.conftest import MakeTestUser, create_test_user
from tests.external_dependency_unit.integrations.conftest import (
    MakeIntegration,
    add_connection,
)


def test_status_four_states_and_moving_credentials(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    import_flag: Callable[[bool], None],
) -> None:
    individual = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    shared = make_integration(
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    user = make_test_user("status")

    import_flag(False)
    status = integration_status(individual, user, db_session)
    assert status.state is ConnectionState.NOT_CONNECTED
    assert status.moving_credentials is True

    import_flag(True)
    status = integration_status(shared, user, db_session)
    assert status.state is ConnectionState.NOT_SET_UP
    assert status.reason == (
        f"{shared.name} is not set up for your organization. Ask your admin."
    )
    assert status.moving_credentials is False

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

    none_mode = make_integration(auth_mode=IntegrationAuthMode.NONE, auth_method=None)
    assert (
        integration_status(none_mode, None, db_session).state
        is ConnectionState.CONNECTED
    )


def test_oauth_without_client_id_is_not_set_up(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    user = make_test_user("no_client")
    manual = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.MANUAL,
    )
    assert integration_status(manual, user, db_session).state is (
        ConnectionState.NOT_SET_UP
    )
    # Discovery registers a client at the first sign-in.
    discovery = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.DISCOVERY,
    )
    assert integration_status(discovery, user, db_session).state is (
        ConnectionState.NOT_CONNECTED
    )


def test_client_id_change_resets_connections_but_secret_change_does_not(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.MANUAL,
        client_id="client-1",
        client_secret="secret-1",
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
        if sign_in_settings_changed(before, after):
            mark_sign_in_settings_changed(integration.id, db_session)
        db_session.commit()

    apply_edit("client-1", "secret-2")
    statuses = {
        connection.status
        for connection in list_connections_for_integration(db_session, integration.id)
    }
    assert statuses == {IntegrationConnectionStatus.CONNECTED}

    apply_edit("client-2", "secret-2")
    connections = list_connections_for_integration(db_session, integration.id)
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
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = make_integration(
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

    assert disconnect(integration, user, db_session) is True
    assert get_connection(db_session, integration.id, user.id) is None
    assert get_connection(db_session, integration.id, other.id) is not None
    assert disconnect(integration, user, db_session) is False


def test_deactivation_deletes_connections(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    user = make_test_user("deactivate")
    add_connection(
        db_session, integration, user.id, ConnectionSecret(fields={"a": "1"})
    )

    deactivate_user(user, db_session)

    assert get_connection(db_session, integration.id, user.id) is None


def test_deleted_user_rows_go_by_cascade(
    db_session: Session, make_integration: MakeIntegration
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    user = create_test_user(db_session, "cascade")
    user_id = user.id
    add_connection(
        db_session, integration, user_id, ConnectionSecret(fields={"a": "1"})
    )

    db_session.execute(
        delete(User__UserGroup).where(User__UserGroup.user_id == user_id)
    )
    db_session.execute(delete(User).where(User.__table__.c.id == user_id))
    db_session.commit()

    assert (
        db_session.scalars(
            select(IntegrationConnection).where(
                IntegrationConnection.user_id == user_id
            )
        ).first()
        is None
    )
