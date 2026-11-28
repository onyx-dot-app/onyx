"""The credential of an MCP call that runs after chat tool construction, and
the Needs reconnect mark when the service rejects an API key."""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
)
from onyx.db.integration_connection import get_connection_by_id
from onyx.db.models import Integration, User
from onyx.integrations.call_credentials import (
    mark_credential_rejected,
    resolve_call_credentials,
    resolve_fresh_call_credentials,
)
from onyx.integrations.connection_models import (
    ConnectionSecret,
    ConnectionState,
    access_token_fingerprint,
)
from onyx.integrations.connections import ConnectionProblem
from onyx.integrations.models import CallCredentials
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    make_mcp_integration,
)
from tests.external_dependency_unit.integrations.conftest import add_connection

SERVER_URL = "https://mcp.example.com/mcp"


@pytest.fixture
def integration(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[Integration, None, None]:
    integration, _ = make_mcp_integration(
        db_session,
        server_url=SERVER_URL,
        name="keys",
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"Authorization": "Bearer {api_key}"},
    )
    try:
        yield integration
    finally:
        delete_integrations(db_session, [integration.id])


def _credentials(
    db_session: Session, integration: Integration, user: User
) -> CallCredentials:
    credentials = resolve_call_credentials(integration, user, db_session)
    if isinstance(credentials, ConnectionProblem):
        pytest.fail(f"expected credentials, got {credentials}")
    return credentials


def _status(db_session: Session, connection_id: int) -> IntegrationConnectionStatus:
    db_session.expire_all()
    connection = get_connection_by_id(db_session, connection_id)
    assert connection is not None
    return connection.status


def test_a_rejected_key_needs_reconnect_but_its_replacement_stays(
    db_session: Session, integration: Integration, make_test_user: MakeTestUser
) -> None:
    rejected = make_test_user("rejected_key")
    replaced = make_test_user("replaced_key")
    for user in (rejected, replaced):
        add_connection(
            db_session, integration, user.id, ConnectionSecret(fields={"api_key": "a"})
        )
    rejected_call = _credentials(db_session, integration, rejected)
    replaced_call = _credentials(db_session, integration, replaced)
    # The user saves a new key while the call with the old key runs.
    replacement = add_connection(
        db_session, integration, replaced.id, ConnectionSecret(fields={"api_key": "b"})
    )

    mark_credential_rejected(rejected_call)
    mark_credential_rejected(replaced_call)

    assert rejected_call.connection_id is not None
    assert (
        _status(db_session, rejected_call.connection_id)
        is IntegrationConnectionStatus.NEEDS_RECONNECT
    )
    assert replaced_call.connection_id == replacement.id
    assert _status(db_session, replacement.id) is IntegrationConnectionStatus.CONNECTED


def test_a_rejected_oauth_token_needs_reconnect(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        server_url=SERVER_URL,
        name="tokens",
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={"Authorization": "Bearer {access_token}"},
    )
    try:
        user = make_test_user("rejected_token")
        add_connection(
            db_session, integration, user.id, ConnectionSecret(access_token="t")
        )
        call = _credentials(db_session, integration, user)

        mark_credential_rejected(call)

        assert call.connection_id is not None
        assert (
            _status(db_session, call.connection_id)
            is IntegrationConnectionStatus.NEEDS_RECONNECT
        )
    finally:
        delete_integrations(db_session, [integration.id])


def test_a_call_that_resolves_again_reads_the_current_rows(
    db_session: Session, integration: Integration, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("fresh_call")
    add_connection(
        db_session, integration, user.id, ConnectionSecret(fields={"api_key": "a"})
    )

    fresh = resolve_fresh_call_credentials(integration.id, user.id)
    integration.enabled = False
    db_session.commit()
    disabled = resolve_fresh_call_credentials(integration.id, user.id)

    assert not isinstance(fresh, ConnectionProblem)
    assert fresh.headers == {"Authorization": "Bearer a"}
    assert isinstance(disabled, ConnectionProblem)
    assert disabled.code is ConnectionState.NOT_SET_UP


def test_a_rejected_renewed_token_needs_reconnect_but_a_new_grant_stays(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    """The MCP SDK can renew the token during the call, so the server can
    reject a token that the call credentials do not hold."""
    integration, _ = make_mcp_integration(
        db_session,
        server_url=SERVER_URL,
        name="renewed_tokens",
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={"Authorization": "Bearer {access_token}"},
    )
    try:
        renewed = make_test_user("renewed_token")
        regranted = make_test_user("regranted_token")
        calls: list[CallCredentials] = []
        for user in (renewed, regranted):
            add_connection(
                db_session, integration, user.id, ConnectionSecret(access_token="old")
            )
            calls.append(_credentials(db_session, integration, user))
            # The call renews the token, and the server rejects the new one.
            add_connection(
                db_session, integration, user.id, ConnectionSecret(access_token="new")
            )
        # The user signs in again before the rejection is recorded.
        add_connection(
            db_session, integration, regranted.id, ConnectionSecret(access_token="b")
        )

        for call in calls:
            mark_credential_rejected(
                call, rejected_token_fingerprint=access_token_fingerprint("new")
            )

        renewed_call, regranted_call = calls
        assert renewed_call.connection_id is not None
        assert regranted_call.connection_id is not None
        assert (
            _status(db_session, renewed_call.connection_id)
            is IntegrationConnectionStatus.NEEDS_RECONNECT
        )
        assert (
            _status(db_session, regranted_call.connection_id)
            is IntegrationConnectionStatus.CONNECTED
        )
    finally:
        delete_integrations(db_session, [integration.id])
