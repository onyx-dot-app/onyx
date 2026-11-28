"""The host values of a preset, such as the Zendesk subdomain, come from the
OAuth client only: ``additional_params`` in the new format, the tagged
registration in the old one. The old copy on the external app is not read.
A change of a host value resets the connections; another edit keeps them."""

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from mitmproxy import http
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationLegacyFormat,
    IntegrationOAuthProviderMode,
    PluginInstallationPolicy,
)
from onyx.db.integration_connection import get_oauth_client
from onyx.db.models import ExternalApp, Integration, IntegrationConnection, User
from onyx.external_apps.matching.engine import AllMatchedActions
from onyx.integrations.call_credentials import resolve_call_credentials
from onyx.integrations.chat_tools import build_integration_chat_tools
from onyx.integrations.connection_models import (
    ConnectionSecret,
    ConnectionState,
    read_connection,
)
from onyx.integrations.connections import (
    ConnectionProblem,
    preset_host_values,
    preset_organization_values,
)
from onyx.integrations.models import ActionSettings, ApprovalMode, LinkValue
from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.models import InjectionContext
from onyx.sandbox_proxy.request_evaluator import IntegrationRequestEvaluator
from onyx.sandbox_proxy.resolvers.integration import IntegrationResolver
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox
from onyx.server.features.integrations import admin_api
from onyx.server.features.integrations.models import (
    IntegrationCreate,
    IntegrationUpdate,
    OAuthClientInput,
    PresetConfigInput,
)
from onyx.tools.models import IntegrationChatRequest, IntegrationLinkConfiguration
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    give_access,
    make_app_integration,
)
from tests.external_dependency_unit.integrations.conftest import (
    add_connection,
    new_oauth_client,
)

_STALE = {"subdomain": "stale", "client_id": "stale-client"}


def _with_stale_app(db_session: Session, integration: Integration) -> None:
    app = db_session.get(ExternalApp, integration.external_app_id)
    assert app is not None
    app.app_type = ExternalAppType.ZENDESK
    app.organization_credentials = _STALE  # ty: ignore[invalid-assignment]
    db_session.commit()


def test_new_format_preset_reads_additional_params(
    db_session: Session,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.PRESET,
            client_id="zd-client",
            client_secret="zd-secret",
        ),
    )
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    oauth_client.additional_params = {"subdomain": "acme"}
    db_session.commit()
    _with_stale_app(db_session, integration)

    assert preset_host_values(integration, db_session) == {"subdomain": "acme"}
    assert preset_organization_values(integration.id, db_session) == {
        "subdomain": "acme",
        "client_id": "zd-client",
    }


def test_legacy_preset_reads_the_tagged_registration(
    db_session: Session,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.PRESET,
            registration={
                "client_id": "zd-client",
                "client_secret": "zd-secret",
                "subdomain": "acme",
            },
        ),
    )
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    oauth_client.legacy_format = IntegrationLegacyFormat.EXTERNAL_APP_ORG.value
    db_session.commit()
    _with_stale_app(db_session, integration)

    assert preset_host_values(integration, db_session) == {"subdomain": "acme"}
    assert preset_organization_values(integration.id, db_session) == {
        "subdomain": "acme",
        "client_id": "zd-client",
    }


def test_the_old_app_copy_is_not_read(
    db_session: Session,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
    )
    _with_stale_app(db_session, integration)

    assert preset_host_values(integration, db_session) == {}
    assert preset_organization_values(integration.id, db_session) == {}


def test_authorize_params_of_a_manual_client_are_no_host_values(
    db_session: Session,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.MANUAL, client_id="c"
        ),
    )
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    oauth_client.additional_params = {"prompt": "consent"}
    db_session.commit()

    assert preset_host_values(integration, db_session) == {}


# A host change through the admin API


_HOST_CREDENTIALS = {
    "subdomain": "acme",
    "client_id": "zd-client",
    "client_secret": "zd-secret",
}


def _zendesk(
    db_session: Session, admin: User, auth_mode: IntegrationAuthMode, legacy: bool
) -> Integration:
    """A Zendesk preset that each user runs. ``legacy``: the OAuth client
    keeps the format that the upgrade copied."""
    detail = admin_api.create_integration(
        IntegrationCreate(
            for_organization=True,
            name=f"zendesk-{uuid4().hex[:8]}",
            auth_mode=auth_mode,
            auth_method=IntegrationAuthMethod.OAUTH2,
            oauth_client=OAuthClientInput(
                provider_mode=IntegrationOAuthProviderMode.PRESET
            ),
            config=PresetConfigInput(
                preset_id="ZENDESK", organization_credentials=_HOST_CREDENTIALS
            ),
        ),
        admin,
        db_session,
    )
    integration = db_session.get(Integration, detail.id)
    assert integration is not None
    if legacy:
        oauth_client = get_oauth_client(db_session, detail.id)
        assert oauth_client is not None
        oauth_client.legacy_format = IntegrationLegacyFormat.EXTERNAL_APP_ORG.value
        oauth_client.client_id = None
        oauth_client.client_secret = None
        oauth_client.additional_params = None
        oauth_client.registration = _HOST_CREDENTIALS  # ty: ignore[invalid-assignment]
    give_access(
        db_session, [integration], installation_policy=PluginInstallationPolicy.DEFAULT
    )
    db_session.commit()
    return integration


def _update(
    db_session: Session, admin: User, integration_id: int, **fields: Any
) -> None:
    admin_api.update_integration(
        integration_id, IntegrationUpdate(**fields), admin, db_session
    )
    db_session.expire_all()


def _config(subdomain: str, client_secret: str) -> PresetConfigInput:
    return PresetConfigInput(
        preset_id="ZENDESK",
        organization_credentials={
            **_HOST_CREDENTIALS,
            "subdomain": subdomain,
            "client_secret": client_secret,
        },
    )


def _chat_tool_names(
    db_session: Session, integration: Integration, user: User
) -> list[str]:
    return [
        tool.name
        for tool in build_integration_chat_tools(
            db_session,
            user,
            IntegrationChatRequest(
                persona_id=7,
                integration_links=[
                    IntegrationLinkConfiguration(
                        integration_id=integration.id,
                        action_settings=ActionSettings(default=LinkValue.ALLOW),
                    )
                ],
                approval_mode=ApprovalMode.INTERACTIVE,
            ),
        )
    ]


def _proxy_headers(
    request: http.Request, user: User, matched: AllMatchedActions
) -> dict[str, str]:
    sandbox = ResolvedSandbox(
        sandbox_id=uuid4(),
        user_id=user.id,
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        sandbox_name="sandbox-preset-host",
        sandbox_ip="10.0.0.1",
    )
    return IntegrationResolver().resolve(
        request, InjectionContext(sandbox=sandbox, matched_actions=matched)
    )


def _tickets(subdomain: str) -> http.Request:
    return http.Request.make("GET", f"https://{subdomain}.zendesk.com/api/v2/tickets")


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    "auth_mode", [IntegrationAuthMode.INDIVIDUAL, IntegrationAuthMode.SHARED]
)
def test_only_a_host_change_resets_the_connections_of_a_preset(
    db_session: Session,
    make_test_user: MakeTestUser,
    auth_mode: IntegrationAuthMode,
    legacy: bool,
) -> None:
    """A credential of the old host never goes to the new one. Another edit,
    also a save of the same host with a new client secret, keeps each
    connection."""
    admin = make_test_user("preset-host-admin", is_admin=True)
    member = make_test_user("preset-host-member")
    integration = _zendesk(db_session, admin, auth_mode, legacy)
    add_connection(
        db_session,
        integration,
        member.id if auth_mode is IntegrationAuthMode.INDIVIDUAL else None,
        ConnectionSecret(access_token="zd-token", refresh_token="zd-refresh"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    connection_ids = [
        connection.id
        for connection in db_session.scalars(
            select(IntegrationConnection).where(
                IntegrationConnection.integration_id == integration.id
            )
        )
    ]
    old_request = _tickets("acme")
    stale_match = IntegrationRequestEvaluator().evaluate(
        old_request, POSTGRES_DEFAULT_SCHEMA, member.id
    )
    assert isinstance(stale_match, AllMatchedActions)

    with patch(
        "onyx.external_apps.providers.base.requests.post",
        side_effect=AssertionError("a refresh call left Onyx"),
    ):
        _update(db_session, admin, integration.id, name=f"renamed-{uuid4().hex[:6]}")
        _update(db_session, admin, integration.id, description="Tickets")
        _update(db_session, admin, integration.id, users_can_save_always_allow=False)
        _update(db_session, admin, integration.id, config=_config("acme", "new-secret"))

        for connection_id in connection_ids:
            connection = db_session.get(IntegrationConnection, connection_id)
            assert connection is not None
            record = read_connection(connection)
            assert record.status is IntegrationConnectionStatus.CONNECTED
            assert record.secret.access_token == "zd-token"
            assert record.secret.refresh_token == "zd-refresh"
        credentials = resolve_call_credentials(integration, member, db_session)
        assert not isinstance(credentials, ConnectionProblem)
        assert credentials.headers == {"Authorization": "Bearer zd-token"}
        assert _proxy_headers(old_request, member, stale_match) == {
            "Authorization": "Bearer zd-token"
        }
        connected_tools = _chat_tool_names(db_session, integration, member)
        assert connected_tools
        assert f"app__{integration.id}__connect" not in connected_tools

        # A resolve would now refresh the token at the token URL of the host.
        for connection_id in connection_ids:
            connection = db_session.get(IntegrationConnection, connection_id)
            assert connection is not None
            connection.expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
        db_session.commit()
        _update(
            db_session, admin, integration.id, config=_config("other", "new-secret")
        )

        for connection_id in connection_ids:
            connection = db_session.get(IntegrationConnection, connection_id)
            assert connection is not None
            assert (
                read_connection(connection).status
                is IntegrationConnectionStatus.NEEDS_RECONNECT
            )
        assert preset_host_values(integration, db_session) == {"subdomain": "other"}
        problem = resolve_call_credentials(integration, member, db_session)
        assert isinstance(problem, ConnectionProblem)
        assert problem.code is ConnectionState.NEEDS_RECONNECT
        assert _chat_tool_names(db_session, integration, member) == [
            f"app__{integration.id}__connect"
        ]

        # The sandbox proxy: the new host gets no credential, and a request
        # that the gate matched to the old host before the change gets none.
        new_request = _tickets("other")
        new_match = IntegrationRequestEvaluator().evaluate(
            new_request, POSTGRES_DEFAULT_SCHEMA, member.id
        )
        assert isinstance(new_match, AllMatchedActions)
        assert new_match.target.integration_id == integration.id
        with pytest.raises(CredentialUnavailableError):
            _proxy_headers(new_request, member, new_match)
        assert (
            IntegrationRequestEvaluator().evaluate(
                old_request, POSTGRES_DEFAULT_SCHEMA, member.id
            )
            is None
        )
        with pytest.raises(CredentialUnavailableError):
            _proxy_headers(old_request, member, stale_match)
