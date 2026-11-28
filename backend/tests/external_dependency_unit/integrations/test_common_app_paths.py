"""The common paths of an admin who adds an app and a member who uses it in
chat, end to end through the route functions: the stored rows, the actions
and the request that a chat tool sends to a mock upstream."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from graphql import build_schema, introspection_from_schema
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.agents.tools import ToolInvocation
from onyx.db.enums import (
    IntegrationActionPolicyValue,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration import get_api_app_for_integration, list_integration_actions
from onyx.db.models import ApiApp, Integration, IntegrationConnection, User
from onyx.integrations.chat_tools import build_integration_chat_tools
from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.models import ActionSettings, ApprovalMode
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolResult
from onyx.server.features.integrations import admin_api, api
from onyx.server.features.integrations.models import (
    ConnectionFieldsRequest,
    GraphQLIntrospectRequest,
    IntegrationCreate,
    IntegrationShape,
    IntegrationUpdate,
    OAuthClientInput,
    OpenApiConfigInput,
    OpenApiConfigView,
    OpenApiEndpointsRequest,
    PresetConfigInput,
)
from onyx.tools.interface import Tool
from onyx.tools.models import (
    IntegrationChatRequest,
    IntegrationLinkConfiguration,
    ToolContext,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integrations.conftest import add_connection

_SEND = "onyx.tools.tool_implementations.http_request.ssrf_safe_request"
_SPEC_GET = "onyx.integrations.service.ssrf_safe_get"
ALLOW = IntegrationActionPolicyValue.ALLOW
ASK = IntegrationActionPolicyValue.ASK

PETS_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Pets", "version": "1"},
    "servers": [{"url": "https://pets.example.com/v1"}],
    "paths": {
        "/pets/{petId}": {
            "get": {
                "operationId": "getPet",
                "summary": "Get a pet",
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            }
        },
        "/pets": {"post": {"operationId": "createPet", "summary": "Create a pet"}},
    },
}
PETS_LINES = ["GET /pets/{petId} Get a pet", "POST /pets Create a pet"]

GRAPHQL_ENDPOINT = "https://tickets.example.com/graphql"
GRAPHQL_SDL = """
type Ticket { id: ID! title: String! }
type Query { ticket(id: ID!): Ticket }
type Mutation { ticketClose(id: ID!): Ticket }
"""


@dataclass
class Sent:
    method: str
    url: str
    headers: dict[str, str]
    body: Any


class MockUpstream:
    """Stands in for each HTTP request a tool sends; records it."""

    def __init__(self, body: Any = None) -> None:
        self.sent: list[Sent] = []
        self.body = json.dumps({"ok": True} if body is None else body).encode()

    def __call__(
        self, url: str, *, method: str, headers: dict[str, str], **kwargs: Any
    ) -> MagicMock:
        self.sent.append(Sent(method.upper(), url, dict(headers), kwargs.get("json")))
        response = MagicMock()
        response.is_redirect = False
        response.status_code = 200
        response.headers = {"Content-Type": "application/json"}
        response.raw.read1.side_effect = [self.body, b""]
        return response


@contextmanager
def _upstream(body: Any = None) -> Generator[MockUpstream, None, None]:
    upstream = MockUpstream(body)
    with patch(_SEND, side_effect=upstream):
        yield upstream


@pytest.fixture
def admin(make_test_user: MakeTestUser) -> User:
    return make_test_user("paths-admin", is_admin=True)


@pytest.fixture
def member(make_test_user: MakeTestUser) -> User:
    return make_test_user("paths-member")


@pytest.fixture
def scoped(make_test_user: MakeTestUser, db_session: Session) -> User:
    user = make_test_user("paths-scoped")
    user.is_group_manager = True
    db_session.commit()
    return user


def _tools(db_session: Session, user: User, integration_id: int) -> dict[str, Tool]:
    tools = build_integration_chat_tools(
        db_session,
        user,
        IntegrationChatRequest(
            persona_id=7,
            integration_links=[
                IntegrationLinkConfiguration(
                    integration_id=integration_id, action_settings=ActionSettings()
                )
            ],
            approval_mode=ApprovalMode.INTERACTIVE,
            chat_session_id=uuid4(),
        ),
    )
    return {
        tool.integration_action.action
        if tool.integration_action is not None
        else tool.name: tool
        for tool in tools
    }


def _call(tool: Tool, **arguments: Any) -> ToolResult:
    result = tool.run(
        ToolInvocation(
            call_id="call",
            arguments=arguments,
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        ToolContext(),
    )
    assert isinstance(result, ToolResult)
    return result


def _policies(db_session: Session, integration_id: int) -> dict[str, Any]:
    return {
        action.key: action.default_policy
        for action in list_integration_actions(integration_id, db_session)
    }


def _fake_spec_get(document: bytes) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.raw.read1.side_effect = [document, b""]
    get = MagicMock()
    get.return_value.__enter__.return_value = response
    return get


def _rest_config(source: str) -> OpenApiConfigInput:
    """The config that the Add modal sends for a spec URL or typed lines."""
    if source == "lines":
        return OpenApiConfigInput(
            base_url="https://pets.example.com/v1", endpoints=PETS_LINES
        )
    with patch(_SPEC_GET, _fake_spec_get(json.dumps(PETS_SPEC).encode())) as get:
        view = admin_api.import_openapi_spec(
            OpenApiEndpointsRequest(spec_url="https://pets.example.com/spec.json"),
            MagicMock(),
        )
    assert get.call_args.args == ("https://pets.example.com/spec.json",)
    assert view.base_url == "https://pets.example.com/v1"
    return OpenApiConfigInput(
        openapi_document=view.openapi_document,
        base_url=view.base_url,
        endpoints=view.endpoints,
    )


@pytest.mark.parametrize("source", ["spec_url", "lines"])
def test_a_rest_app_from_each_source_calls_its_url_with_the_key(
    db_session: Session, admin: User, member: User, source: str
) -> None:
    detail = admin_api.create_integration(
        IntegrationCreate(
            for_organization=True,
            name=f"pets-{uuid4().hex[:8]}",
            auth_mode=IntegrationAuthMode.SHARED,
            auth_method=IntegrationAuthMethod.API_KEY,
            header_template={"X-Api-Key": "{api_key}"},
            config=_rest_config(source),
        ),
        admin,
        db_session,
    )
    assert detail.shape is IntegrationShape.OPENAPI
    api_app = get_api_app_for_integration(detail.id, db_session)
    assert api_app is not None and api_app.base_url == "https://pets.example.com/v1"
    policies = _policies(db_session, detail.id)
    (get_key,) = [key for key in policies if "get" in key.lower()]
    (post_key,) = [key for key in policies if key != get_key]
    assert (policies[get_key], policies[post_key]) == (ALLOW, ASK)

    # A member sees only the connect tool until the admin saves the key.
    assert list(_tools(db_session, member, detail.id)) == [f"app__{detail.id}__connect"]
    admin_api.save_organization_connection(
        detail.id,
        ConnectionFieldsRequest(fields={"api_key": "org-key-1"}),
        admin,
        db_session,
    )
    tools = _tools(db_session, member, detail.id)
    assert tools[get_key].approval is None
    assert tools[post_key].approval is not None
    with _upstream() as upstream:
        result = _call(tools[get_key], petId="7")
    assert not result.is_error, result.content
    (sent,) = upstream.sent
    assert (sent.method, sent.url) == ("GET", "https://pets.example.com/v1/pets/7")
    assert sent.headers["X-Api-Key"] == "org-key-1"

    # The admin edits the endpoints and the base URL on the Configuration tab.
    view = admin_api.get_integration_admin(detail.id, admin, db_session).config
    assert isinstance(view, OpenApiConfigView)
    admin_api.update_integration(
        detail.id,
        IntegrationUpdate(
            config=OpenApiConfigInput(
                openapi_document=view.openapi_document,
                base_url="https://pets2.example.com/v2",
                endpoints=[*view.endpoints, "DELETE /pets/{petId} Delete a pet"],
            )
        ),
        admin,
        db_session,
    )
    db_session.expire_all()
    api_app = get_api_app_for_integration(detail.id, db_session)
    assert api_app is not None and api_app.base_url == "https://pets2.example.com/v2"
    policies = _policies(db_session, detail.id)
    (delete_key,) = [key for key in policies if "delete" in key.lower()]
    assert policies[delete_key] is ASK and policies[get_key] is ALLOW
    # The key was for the old host: it must not go to the new one.
    assert list(_tools(db_session, member, detail.id)) == [f"app__{detail.id}__connect"]
    admin_api.save_organization_connection(
        detail.id,
        ConnectionFieldsRequest(fields={"api_key": "org-key-2"}),
        admin,
        db_session,
    )
    with _upstream() as upstream:
        _call(_tools(db_session, member, detail.id)[get_key], petId="8")
    (sent,) = upstream.sent
    assert sent.url == "https://pets2.example.com/v2/pets/8"
    assert sent.headers["X-Api-Key"] == "org-key-2"

    api_app_id = api_app.id
    admin_api.delete_integration(detail.id, admin, db_session)
    db_session.expire_all()
    assert db_session.get(Integration, detail.id) is None
    assert db_session.get(ApiApp, api_app_id) is None
    assert not db_session.scalars(
        select(IntegrationConnection).where(
            IntegrationConnection.integration_id == detail.id
        )
    ).all()


@pytest.mark.parametrize("sign_in", ["none", "api_key", "oauth"])
def test_each_sign_in_sends_the_credential_of_the_member(
    db_session: Session, admin: User, member: User, sign_in: str
) -> None:
    create = IntegrationCreate(
        for_organization=True,
        name=f"pets-{uuid4().hex[:8]}",
        auth_mode=IntegrationAuthMode.NONE,
        config=OpenApiConfigInput(openapi_document=json.dumps(PETS_SPEC)),
    )
    if sign_in == "api_key":
        create.auth_mode = IntegrationAuthMode.INDIVIDUAL
        create.auth_method = IntegrationAuthMethod.API_KEY
        create.header_template = {"Authorization": "Token {api_key}"}
    elif sign_in == "oauth":
        create.auth_mode = IntegrationAuthMode.INDIVIDUAL
        create.auth_method = IntegrationAuthMethod.OAUTH2
        create.oauth_client = OAuthClientInput(
            provider_mode=IntegrationOAuthProviderMode.MANUAL,
            authorization_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            client_id="client",
            client_secret="secret",
        )
    detail = admin_api.create_integration(create, admin, db_session)

    if sign_in == "api_key":
        api.save_member_connection(
            detail.id,
            ConnectionFieldsRequest(fields={"api_key": "member-key"}),
            member,
            db_session,
        )
    elif sign_in == "oauth":
        integration = db_session.get(Integration, detail.id)
        assert integration is not None
        # What the OAuth callback stores; test_oauth_flow covers the callback.
        add_connection(
            db_session, integration, member.id, ConnectionSecret(access_token="tok")
        )
    with _upstream() as upstream:
        _call(_tools(db_session, member, detail.id)["getPet"], petId="7")
    (sent,) = upstream.sent
    expected = {"none": None, "api_key": "Token member-key", "oauth": "Bearer tok"}
    assert sent.headers.get("Authorization") == expected[sign_in]

    if sign_in != "none":
        # The member disconnects: only the connect tool stays.
        api.delete_member_connection(detail.id, member, db_session)
        assert list(_tools(db_session, member, detail.id)) == [
            f"app__{detail.id}__connect"
        ]


def test_a_graphql_app_from_introspection_sends_the_document_with_the_key(
    db_session: Session, admin: User, member: User
) -> None:
    introspection = {"data": introspection_from_schema(build_schema(GRAPHQL_SDL))}
    with _upstream(introspection) as upstream:
        config = admin_api.introspect_graphql(
            GraphQLIntrospectRequest(endpoint_url=GRAPHQL_ENDPOINT), MagicMock()
        )
    (sent,) = upstream.sent
    assert (sent.method, sent.url) == ("POST", GRAPHQL_ENDPOINT)
    assert "__schema" in sent.body["query"]
    assert "ticketClose" in config.graphql_schema

    detail = admin_api.create_integration(
        IntegrationCreate(
            for_organization=True,
            name=f"tickets-{uuid4().hex[:8]}",
            auth_mode=IntegrationAuthMode.SHARED,
            auth_method=IntegrationAuthMethod.API_KEY,
            header_template={"Authorization": "Bearer {api_key}"},
            config=config,
        ),
        admin,
        db_session,
    )
    admin_api.save_organization_connection(
        detail.id, ConnectionFieldsRequest(fields={"api_key": "gql"}), admin, db_session
    )
    tools = _tools(db_session, member, detail.id)
    with _upstream({"data": {"ticket": {"id": "7"}}}) as upstream:
        result = _call(tools["query.ticket"], id="7")
    assert not result.is_error, result.content
    (sent,) = upstream.sent
    assert (sent.method, sent.url) == ("POST", GRAPHQL_ENDPOINT)
    assert sent.headers["Authorization"] == "Bearer gql"
    assert sent.body == {
        "query": "query($id: ID!) { ticket(id: $id) { id title } }",
        "variables": {"id": "7"},
    }


@pytest.mark.parametrize("for_organization", [True, False])
def test_a_preset_app_runs_its_actions_with_the_users_own_token(
    db_session: Session,
    admin: User,
    member: User,
    scoped: User,
    for_organization: bool,
) -> None:
    """An admin adds Linear for the organization and a member connects; or a
    scoped manager adds it for themselves and connects."""
    creator, user = (admin, member) if for_organization else (scoped, scoped)
    detail = admin_api.create_integration(
        IntegrationCreate(
            for_organization=for_organization,
            name=f"linear-{uuid4().hex[:8]}",
            auth_mode=IntegrationAuthMode.INDIVIDUAL,
            auth_method=IntegrationAuthMethod.OAUTH2,
            oauth_client=OAuthClientInput(
                provider_mode=IntegrationOAuthProviderMode.PRESET
            ),
            config=PresetConfigInput(
                preset_id="LINEAR",
                organization_credentials={"client_id": "c", "client_secret": "s"},
            ),
        ),
        creator,
        db_session,
    )
    assert detail.shape is IntegrationShape.PRESET
    assert [
        view.id
        for view in api.list_integrations_for_member(user, db_session)
        if view.id == detail.id
    ] == [detail.id]
    if not for_organization:
        # A personal app stays hidden from other members.
        assert detail.id not in {
            view.id for view in api.list_integrations_for_member(member, db_session)
        }
    assert list(_tools(db_session, user, detail.id)) == [f"app__{detail.id}__connect"]

    integration = db_session.get(Integration, detail.id)
    assert integration is not None
    add_connection(
        db_session, integration, user.id, ConnectionSecret(access_token="user-tok")
    )
    tools = _tools(db_session, user, detail.id)
    assert tools["linear.issues.read"].approval is None
    assert tools["linear.issues.create"].approval is not None
    assert tools["unspecified"].approval is not None
    query = {"query": "{ issues { nodes { id } } }"}
    with _upstream({"data": {"issues": {"nodes": []}}}) as upstream:
        result = _call(
            tools["linear.issues.read"],
            method="POST",
            url="https://api.linear.app/graphql",
            body=query,
        )
        other = _call(
            tools["unspecified"],
            method="POST",
            url="https://api.linear.app/graphql",
            body={"query": "{ organization { id } }"},
        )
    assert not result.is_error and not other.is_error, (result, other)
    assert [(sent.url, sent.headers["Authorization"]) for sent in upstream.sent] == [
        ("https://api.linear.app/graphql", "Bearer user-tok")
    ] * 2
    assert upstream.sent[0].body == query
