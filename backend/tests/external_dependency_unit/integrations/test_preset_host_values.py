"""The host values of a preset, such as the Zendesk subdomain, come from the
OAuth client only: ``additional_params`` in the new format, the tagged
registration in the old one. The old copy on the external app is not read."""

from collections.abc import Generator

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationLegacyFormat,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration_connection import get_oauth_client
from onyx.db.models import ExternalApp, Integration
from onyx.integrations.connections import (
    preset_host_values,
    preset_organization_values,
)
from tests.external_dependency_unit.integrations.conftest import MakeIntegration

_STALE = {"subdomain": "stale", "client_id": "stale-client"}


@pytest.fixture
def zendesk_app(
    db_session: Session,
) -> Generator[list[ExternalApp], None, None]:
    apps: list[ExternalApp] = []
    yield apps
    db_session.rollback()
    db_session.execute(
        delete(ExternalApp).where(ExternalApp.id.in_([app.id for app in apps]))
    )
    db_session.commit()


def _with_stale_app(
    db_session: Session, integration: Integration, apps: list[ExternalApp]
) -> None:
    app = ExternalApp(
        name=f"Zendesk {integration.id}",
        app_type=ExternalAppType.ZENDESK,
        upstream_url_patterns=[],
        auth_template={"Authorization": "Bearer {access_token}"},
        organization_credentials=_STALE,
        integration_id=integration.id,
    )
    db_session.add(app)
    db_session.commit()
    apps.append(app)


def test_new_format_preset_reads_additional_params(
    db_session: Session,
    make_integration: MakeIntegration,
    zendesk_app: list[ExternalApp],
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.PRESET,
        client_id="zd-client",
        client_secret="zd-secret",
    )
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    oauth_client.additional_params = {"subdomain": "acme"}
    db_session.commit()
    _with_stale_app(db_session, integration, zendesk_app)

    assert preset_host_values(integration, db_session) == {"subdomain": "acme"}
    assert preset_organization_values(integration.id, db_session) == {
        "subdomain": "acme",
        "client_id": "zd-client",
    }


def test_legacy_preset_reads_the_tagged_registration(
    db_session: Session,
    make_integration: MakeIntegration,
    zendesk_app: list[ExternalApp],
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.PRESET,
        registration={
            "client_id": "zd-client",
            "client_secret": "zd-secret",
            "subdomain": "acme",
        },
    )
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    oauth_client.legacy_format = IntegrationLegacyFormat.EXTERNAL_APP_ORG.value
    db_session.commit()
    _with_stale_app(db_session, integration, zendesk_app)

    assert preset_host_values(integration, db_session) == {"subdomain": "acme"}
    assert preset_organization_values(integration.id, db_session) == {
        "subdomain": "acme",
        "client_id": "zd-client",
    }


def test_the_old_app_copy_is_not_read(
    db_session: Session,
    make_integration: MakeIntegration,
    zendesk_app: list[ExternalApp],
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
    )
    _with_stale_app(db_session, integration, zendesk_app)

    assert preset_host_values(integration, db_session) == {}
    assert preset_organization_values(integration.id, db_session) == {}


def test_authorize_params_of_a_manual_client_are_no_host_values(
    db_session: Session, make_integration: MakeIntegration
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.MANUAL,
        client_id="c",
    )
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    oauth_client.additional_params = {"prompt": "consent"}
    db_session.commit()

    assert preset_host_values(integration, db_session) == {}
