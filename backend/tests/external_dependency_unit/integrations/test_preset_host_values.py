"""The host values of a preset, such as the Zendesk subdomain, come from the
OAuth client only: ``additional_params`` in the new format, the tagged
registration in the old one. The old copy on the external app is not read."""

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
from tests.external_dependency_unit.integration_helpers import make_app_integration
from tests.external_dependency_unit.integrations.conftest import new_oauth_client

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
