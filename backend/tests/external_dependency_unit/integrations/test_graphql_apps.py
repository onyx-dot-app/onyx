"""A custom GraphQL app: its root fields become actions, chat tools that
write one-field documents, and proxy matches by root field."""

import json
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    IntegrationAuthMode,
    PluginInstallationPolicy,
)
from onyx.db.integration import list_integration_actions
from onyx.db.models import Integration, User
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.integrations.chat_tools import build_integration_chat_tools
from onyx.integrations.kinds.api import ApiKindHandler
from onyx.integrations.models import ActionSettings, ApprovalMode
from onyx.sandbox_proxy.usable_integrations import load_match_targets
from onyx.server.features.integrations import admin_api
from onyx.server.features.integrations.models import (
    GraphQLConfigInput,
    IntegrationCreate,
    IntegrationShape,
)
from onyx.tools.models import (
    IntegrationChatRequest,
    IntegrationLinkConfiguration,
    ToolCallException,
)
from onyx.tools.tool_implementations.custom.graphql_tool import GraphQLTool
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import give_access

ENDPOINT = "https://tickets.example.com/graphql"
SDL = """
enum State { OPEN CLOSED }
type User { id: ID! name: String }
type Ticket { id: ID! title: String! state: State assignee: User }
type Query {
  "Read a ticket."
  ticket(id: ID!): Ticket
}
type Mutation { ticketClose(id: ID!, reason: String): Ticket }
"""


@pytest.fixture
def admin(make_test_user: MakeTestUser) -> User:
    return make_test_user("graphql-apps-admin", is_admin=True)


@pytest.fixture
def integration(db_session: Session, admin: User) -> Integration:
    detail = admin_api.create_integration(
        IntegrationCreate(
            name=f"tickets-{uuid4().hex[:8]}",
            auth_mode=IntegrationAuthMode.NONE,
            config=GraphQLConfigInput(endpoint_url=ENDPOINT, graphql_schema=SDL),
        ),
        admin,
        db_session,
    )
    assert detail.shape is IntegrationShape.GRAPHQL
    assert detail.config == GraphQLConfigInput(
        endpoint_url=ENDPOINT, graphql_schema=SDL
    )
    integration = db_session.get(Integration, detail.id)
    assert integration is not None
    assert integration.tool_id is None and integration.api_app_id is not None
    give_access(
        db_session, [integration], installation_policy=PluginInstallationPolicy.DEFAULT
    )
    db_session.commit()
    return integration


def test_root_fields_become_actions(
    db_session: Session, integration: Integration
) -> None:
    actions = {
        action.key: action
        for action in list_integration_actions(integration.id, db_session)
    }
    assert set(actions) == {"query.ticket", "mutation.ticketClose"}
    assert {action.source for action in actions.values()} == {
        IntegrationActionSource.GRAPHQL
    }
    assert actions["query.ticket"].default_policy is IntegrationActionPolicyValue.ALLOW
    assert actions["query.ticket"].description == "Read a ticket."
    assert (
        actions["mutation.ticketClose"].default_policy
        is IntegrationActionPolicyValue.ASK
    )


def test_tools_send_one_root_field(
    db_session: Session, admin: User, integration: Integration
) -> None:
    tools = build_integration_chat_tools(
        db_session,
        admin,
        IntegrationChatRequest(
            persona_id=7,
            integration_links=[
                IntegrationLinkConfiguration(
                    integration_id=integration.id, action_settings=ActionSettings()
                )
            ],
            approval_mode=ApprovalMode.INTERACTIVE,
        ),
    )
    by_key = {
        tool.integration_action.action: tool
        for tool in tools
        if isinstance(tool, GraphQLTool) and tool.integration_action is not None
    }
    query, mutation = by_key["query.ticket"], by_key["mutation.ticketClose"]
    assert query.approval is None
    assert mutation.approval is not None

    assert query._request({"id": "7"}) == (
        "POST",
        ENDPOINT,
        {
            "query": "query($id: ID!) { ticket(id: $id) { id title state } }",
            "variables": {"id": "7"},
        },
    )
    assert query._request({"id": "7", "selection": "{ assignee { name } }"})[2] == {
        "query": "query($id: ID!) { ticket(id: $id) { assignee { name } } }",
        "variables": {"id": "7"},
    }
    assert mutation._request({"id": "7", "reason": "done"})[2] == {
        "query": (
            "mutation($id: ID!, $reason: String) "
            "{ ticketClose(id: $id, reason: $reason) { id title state } }"
        ),
        "variables": {"id": "7", "reason": "done"},
    }
    assert mutation._request({"id": "7", "selection": "id"})[2] == {
        "query": "mutation($id: ID!) { ticketClose(id: $id) { id } }",
        "variables": {"id": "7"},
    }
    with pytest.raises(ToolCallException):
        query._request({"id": "7", "selection": "{ id } ticket(id: $id) { title }"})


def _matched_keys(
    db_session: Session, integration: Integration, query: str, url: str = ENDPOINT
) -> list[str] | None:
    (target,) = load_match_targets(db_session, integration.id)
    match = ApiKindHandler().match_request(
        integration,
        target,
        ProxiedRequest(
            method="POST",
            path="/graphql",
            url=url,
            body=json.dumps({"query": query}).encode(),
        ),
        db_session,
    )
    return None if match is None else [action.action_key for action in match.actions]


def test_proxy_matches_a_script_request_by_root_field(
    db_session: Session, integration: Integration
) -> None:
    assert _matched_keys(db_session, integration, '{ ticket(id: "7") { id } }') == [
        "query.ticket"
    ]
    assert _matched_keys(
        db_session, integration, 'mutation { ticketClose(id: "7") { id } }'
    ) == ["mutation.ticketClose"]
    # An unknown root field next to a known one also asks.
    assert _matched_keys(
        db_session, integration, '{ ticket(id: "7") { id } other { id } }'
    ) == ["query.ticket", "unspecified"]
    assert _matched_keys(db_session, integration, "not graphql") == ["unspecified"]
    assert (
        _matched_keys(
            db_session, integration, "{ ticket { id } }", "https://other.example.com/"
        )
        is None
    )
