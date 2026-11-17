"""The credential of an MCP call that runs after chat tool construction, and
the Needs reconnect mark when the service rejects an API key."""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    MCPTransport,
)
from onyx.db.integration_connection import get_connection_by_id
from onyx.db.models import Integration, User
from onyx.integrations.call_credentials import (
    mark_api_key_rejected,
    resolve_call_credentials,
    resolve_mcp_call_auth,
)
from onyx.integrations.connection_models import ConnectionSecret, ConnectionState
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

    mark_api_key_rejected(rejected_call)
    mark_api_key_rejected(replaced_call)

    assert rejected_call.connection_id is not None
    assert (
        _status(db_session, rejected_call.connection_id)
        is IntegrationConnectionStatus.NEEDS_RECONNECT
    )
    assert replaced_call.connection_id == replacement.id
    assert _status(db_session, replacement.id) is IntegrationConnectionStatus.CONNECTED


def test_an_mcp_call_sends_no_credential_to_a_server_that_moved(
    db_session: Session, integration: Integration, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("moved_server")
    add_connection(
        db_session, integration, user.id, ConnectionSecret(fields={"api_key": "a"})
    )

    same = resolve_mcp_call_auth(
        integration.id, user.id, MCPTransport.STREAMABLE_HTTP, SERVER_URL
    )
    moved = resolve_mcp_call_auth(
        integration.id,
        user.id,
        MCPTransport.STREAMABLE_HTTP,
        "https://old.example.com/mcp",
    )

    assert not isinstance(same, ConnectionProblem)
    assert same[0].headers == {"Authorization": "Bearer a"}
    assert isinstance(moved, ConnectionProblem)
    assert moved.code is ConnectionState.NOT_SET_UP
