"""Guard the SSO admin API contract: secrets never persist masked, config
merges stay partial, conflicting or missing providers are reported, and only
provider types the deployment can actually route are configurable.

The API must never persist masked secrets as real config values.
"""

from collections.abc import Generator
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, register_onyx_exception_handlers
from onyx.server.manage.sso.api import admin_router
from onyx.utils.encryption import is_masked_credential


@pytest.fixture(autouse=True)
def _stub_idp_url_guard() -> Generator[None, None, None]:
    # Provider CRUD here uses placeholder IdP URLs and must not hit the network.
    # The URL guard itself is covered in test_sso_url_guard.
    with patch("onyx.server.manage.sso.api.validate_idp_url", return_value=None):
        yield


@pytest.fixture()
def client(
    db_session: Session,
    tenant_context: None,
) -> Generator[TestClient, None, None]:
    assert tenant_context is None
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(admin_router)

    app.dependency_overrides[current_user] = lambda: SimpleNamespace(
        effective_permissions=["admin"]
    )

    def override_get_session() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture()
def provider_names(db_session: Session) -> Generator[list[str], None, None]:
    names: list[str] = []
    yield names
    db_session.rollback()
    if names:
        db_session.execute(delete(SSOProvider).where(SSOProvider.name.in_(names)))
    db_session.commit()


@pytest.fixture()
def only_test_providers_enabled(db_session: Session) -> Generator[None, None, None]:
    """Give the multi-SSO count assertions a clean baseline: pre-existing
    enabled providers (e.g. rows on a shared dev database) are disabled for
    the duration of the test and restored afterwards."""
    preexisting_ids = list(
        db_session.scalars(
            select(SSOProvider.id).where(SSOProvider.enabled.is_(True))
        ).all()
    )
    if preexisting_ids:
        for provider in db_session.scalars(
            select(SSOProvider).where(SSOProvider.id.in_(preexisting_ids))
        ):
            provider.enabled = False
        db_session.commit()
    try:
        yield
    finally:
        db_session.rollback()
        if preexisting_ids:
            for provider in db_session.scalars(
                select(SSOProvider).where(SSOProvider.id.in_(preexisting_ids))
            ):
                provider.enabled = True
            db_session.commit()


def _build_oidc_request(name: str, client_secret: str) -> dict[str, Any]:
    return {
        "name": name,
        "display_name": "Company A",
        "provider_type": SSOProviderType.OIDC.value,
        "config": {
            "client_id": "client-id",
            "client_secret": client_secret,
            "openid_config_url": "https://idp.example.com/.well-known/openid-configuration",
        },
        "allowed_email_domains": ["companya.com"],
    }


def _build_saml_request(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "display_name": "Company SAML",
        "provider_type": SSOProviderType.SAML.value,
        "config": {
            "idp_entity_id": "https://idp.example.com/entity",
            "idp_sso_url": "https://idp.example.com/sso",
            "idp_x509_cert": "cert",
            "sp_entity_id": "onyx",
        },
        "allowed_email_domains": ["companya.com"],
    }


def _new_provider_name(prefix: str = "oidc-test") -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def _stored_config(db_session: Session, provider_id: int) -> dict[str, Any]:
    db_session.expire_all()
    stored = db_session.get(SSOProvider, provider_id)
    assert stored is not None and stored.config is not None
    return stored.config.get_value(apply_mask=False)


def _find_provider(providers: list[dict[str, Any]], provider_id: int) -> dict[str, Any]:
    for provider in providers:
        if provider["id"] == provider_id:
            return provider
    raise AssertionError(f"provider {provider_id} not found")


def test_sso_provider_crud_masks_and_restores_secrets(
    client: TestClient,
    db_session: Session,
    provider_names: list[str],
) -> None:
    name = _new_provider_name()
    original_secret = "super-secret-value"

    create_response = client.post(
        "/admin/sso/provider",
        json=_build_oidc_request(name, original_secret),
    )
    assert create_response.status_code == 200
    created_provider = create_response.json()
    assert created_provider["name"] == name
    assert created_provider["display_name"] == "Company A"
    assert created_provider["provider_type"] == SSOProviderType.OIDC.value
    assert created_provider["enabled"] is True
    assert created_provider["allowed_email_domains"] == ["companya.com"]
    assert (
        created_provider["redirect_uri"]
        == f"{WEB_DOMAIN}/api/auth/oidc/{name}/callback"
    )

    masked_secret = created_provider["config"]["client_secret"]
    assert masked_secret != original_secret
    assert is_masked_credential(masked_secret) is True

    # Non-secret fields read back real so an admin can verify the setup.
    assert created_provider["config"]["client_id"] == "client-id"
    assert (
        created_provider["config"]["openid_config_url"]
        == "https://idp.example.com/.well-known/openid-configuration"
    )

    provider_id = created_provider["id"]
    provider_names.append(name)

    list_response = client.get("/admin/sso/provider")
    assert list_response.status_code == 200
    listed_provider = _find_provider(list_response.json(), provider_id)
    assert listed_provider["config"]["client_secret"] == masked_secret
    assert is_masked_credential(listed_provider["config"]["client_secret"]) is True
    assert (
        listed_provider["redirect_uri"] == f"{WEB_DOMAIN}/api/auth/oidc/{name}/callback"
    )

    patch_masked_response = client.patch(
        f"/admin/sso/provider/{provider_id}",
        json={
            "display_name": "Company B",
            "config": {
                "client_id": "client-id",
                "client_secret": masked_secret,
                "openid_config_url": "https://idp.example.com/.well-known/openid-configuration",
            },
        },
    )
    assert patch_masked_response.status_code == 200
    assert patch_masked_response.json()["display_name"] == "Company B"
    assert (
        is_masked_credential(patch_masked_response.json()["config"]["client_secret"])
        is True
    )

    assert _stored_config(db_session, provider_id)["client_secret"] == original_secret

    new_secret = "new-super-secret"
    patch_new_secret_response = client.patch(
        f"/admin/sso/provider/{provider_id}",
        json={
            "config": {
                "client_id": "client-id",
                "client_secret": new_secret,
                "openid_config_url": "https://idp.example.com/.well-known/openid-configuration",
            }
        },
    )
    assert patch_new_secret_response.status_code == 200
    assert patch_new_secret_response.json()["config"]["client_secret"] != new_secret
    assert (
        is_masked_credential(
            patch_new_secret_response.json()["config"]["client_secret"]
        )
        is True
    )

    assert _stored_config(db_session, provider_id)["client_secret"] == new_secret

    disable_response = client.post(
        f"/admin/sso/provider/{provider_id}/enabled",
        json={"enabled": False},
    )
    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False
    assert (
        is_masked_credential(disable_response.json()["config"]["client_secret"]) is True
    )

    disabled_list_response = client.get("/admin/sso/provider")
    assert disabled_list_response.status_code == 200
    disabled_provider = _find_provider(disabled_list_response.json(), provider_id)
    assert disabled_provider["enabled"] is False
    assert is_masked_credential(disabled_provider["config"]["client_secret"]) is True


def test_update_partial_config_preserves_stored_keys(
    client: TestClient,
    db_session: Session,
    provider_names: list[str],
) -> None:
    """A PATCH whose config omits a stored key must not erase it. The omitted
    openid_config_url survives, the sent client_id updates, and the masked
    client_secret restores the stored value."""
    name = _new_provider_name()
    create_response = client.post(
        "/admin/sso/provider",
        json=_build_oidc_request(name, "super-secret-value"),
    )
    assert create_response.status_code == 200
    provider_names.append(name)
    provider_id = create_response.json()["id"]
    masked_secret = create_response.json()["config"]["client_secret"]

    patch_response = client.patch(
        f"/admin/sso/provider/{provider_id}",
        json={"config": {"client_id": "new-client-id", "client_secret": masked_secret}},
    )
    assert patch_response.status_code == 200

    config = _stored_config(db_session, provider_id)
    assert config["client_id"] == "new-client-id"
    assert config["client_secret"] == "super-secret-value"
    assert (
        config["openid_config_url"]
        == "https://idp.example.com/.well-known/openid-configuration"
    )


def test_create_saml_provider(
    client: TestClient,
    db_session: Session,
    provider_names: list[str],
) -> None:
    """SAML providers can be created via the admin API. The redirect URI points
    at the SAML callback and secret config (sp_private_key) is masked on read."""
    name = _new_provider_name(prefix="saml-test")
    response = client.post(
        "/admin/sso/provider",
        json={
            "name": name,
            "display_name": "Company SAML",
            "provider_type": SSOProviderType.SAML.value,
            "config": {
                "idp_entity_id": "https://idp.example.com/entity",
                "idp_sso_url": "https://idp.example.com/sso",
                "idp_x509_cert": "MIIDsamplecertvalue",
                "sp_entity_id": "onyx",
                "sp_private_key": "-----BEGIN PRIVATE KEY-----secret",
            },
            "allowed_email_domains": ["companysaml.com"],
        },
    )
    assert response.status_code == 200
    provider_names.append(name)
    body = response.json()
    assert body["provider_type"] == SSOProviderType.SAML.value
    # Single issuer-resolved ACS for every SAML row, no /api prefix (the
    # AuthnRequest advertises this exact URL).
    assert body["redirect_uri"] == f"{WEB_DOMAIN}/auth/saml/callback"
    assert is_masked_credential(body["config"]["sp_private_key"]) is True
    assert body["config"]["idp_sso_url"] == "https://idp.example.com/sso"
    assert body["config"]["idp_x509_cert"] == "MIIDsamplecertvalue"

    raw = _stored_config(db_session, body["id"])
    assert raw["idp_entity_id"] == "https://idp.example.com/entity"
    assert raw["sp_private_key"] == "-----BEGIN PRIVATE KEY-----secret"


def test_create_rejects_masked_credentials(
    client: TestClient,
    db_session: Session,
) -> None:
    name = _new_provider_name()

    response = client.post(
        "/admin/sso/provider",
        json=_build_oidc_request(name, "••••••••••••"),
    )
    assert response.status_code == OnyxErrorCode.INVALID_INPUT.status_code
    assert response.json()["error_code"] == OnyxErrorCode.INVALID_INPUT.code

    db_session.expire_all()
    stored_provider = db_session.scalars(
        select(SSOProvider).where(SSOProvider.name == name)
    ).first()
    assert stored_provider is None


@pytest.mark.usefixtures("only_test_providers_enabled")
def test_create_duplicate_name_returns_duplicate_resource(
    client: TestClient,
    db_session: Session,
    provider_names: list[str],
) -> None:
    name = _new_provider_name()

    first_response = client.post(
        "/admin/sso/provider",
        json=_build_oidc_request(name, "super-secret-value"),
    )
    assert first_response.status_code == 200
    provider_names.append(name)
    first_id = first_response.json()["id"]

    # Disable the first row so the multi-SSO tier gate cannot fire on the
    # duplicate attempt under license enforcement. Name uniqueness is
    # tier-independent.
    disable_response = client.post(
        f"/admin/sso/provider/{first_id}/enabled",
        json={"enabled": False},
    )
    assert disable_response.status_code == 200

    duplicate_response = client.post(
        "/admin/sso/provider",
        json=_build_oidc_request(name, "another-secret-value"),
    )
    assert (
        duplicate_response.status_code == OnyxErrorCode.DUPLICATE_RESOURCE.status_code
    )
    assert (
        duplicate_response.json()["error_code"] == OnyxErrorCode.DUPLICATE_RESOURCE.code
    )

    db_session.expire_all()
    stored_providers = list(
        db_session.scalars(select(SSOProvider).where(SSOProvider.name == name)).all()
    )
    assert len(stored_providers) == 1


def _auth_disabled_settings() -> SimpleNamespace:
    return SimpleNamespace(password_auth_enabled=False)


def test_cannot_disable_last_provider_when_password_auth_off(
    client: TestClient,
    db_session: Session,
    provider_names: list[str],
) -> None:
    """With password auth already off, disabling the only enabled provider
    would leave no way in, so it's refused and the row stays enabled.

    The enabled-provider count is patched so the guard sees exactly this row,
    independent of any provider rows the shared DB already holds.
    """
    name = _new_provider_name()
    create_response = client.post(
        "/admin/sso/provider",
        json=_build_oidc_request(name, "super-secret-value"),
    )
    assert create_response.status_code == 200
    provider_names.append(name)
    provider_id = create_response.json()["id"]

    with (
        patch(
            "onyx.server.manage.sso.api.load_effective_uncached",
            _auth_disabled_settings,
        ),
        patch(
            "onyx.server.manage.sso.api.fetch_sso_providers",
            return_value=[SimpleNamespace(id=provider_id)],
        ),
    ):
        response = client.post(
            f"/admin/sso/provider/{provider_id}/enabled",
            json={"enabled": False},
        )

    assert response.status_code == OnyxErrorCode.INVALID_INPUT.status_code
    assert response.json()["error_code"] == OnyxErrorCode.INVALID_INPUT.code

    db_session.expire_all()
    stored = db_session.get(SSOProvider, provider_id)
    assert stored is not None
    assert stored.enabled is True


def test_can_disable_provider_when_another_remains_and_auth_off(
    client: TestClient,
    provider_names: list[str],
) -> None:
    """A second enabled provider keeps a login path open, so disabling one is
    allowed even with password auth off."""
    name = _new_provider_name()
    provider_id = client.post(
        "/admin/sso/provider", json=_build_oidc_request(name, "secret-a")
    ).json()["id"]
    provider_names.append(name)

    with (
        patch(
            "onyx.server.manage.sso.api.load_effective_uncached",
            _auth_disabled_settings,
        ),
        patch(
            "onyx.server.manage.sso.api.fetch_sso_providers",
            return_value=[
                SimpleNamespace(id=provider_id),
                SimpleNamespace(id=provider_id + 1),
            ],
        ),
    ):
        response = client.post(
            f"/admin/sso/provider/{provider_id}/enabled",
            json={"enabled": False},
        )

    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_missing_provider_routes_return_not_found(client: TestClient) -> None:
    missing_provider_id = 987654321

    patch_response = client.patch(
        f"/admin/sso/provider/{missing_provider_id}",
        json={"display_name": "Missing"},
    )
    assert patch_response.status_code == OnyxErrorCode.NOT_FOUND.status_code
    assert patch_response.json()["error_code"] == OnyxErrorCode.NOT_FOUND.code

    enabled_response = client.post(
        f"/admin/sso/provider/{missing_provider_id}/enabled",
        json={"enabled": False},
    )
    assert enabled_response.status_code == OnyxErrorCode.NOT_FOUND.status_code
    assert enabled_response.json()["error_code"] == OnyxErrorCode.NOT_FOUND.code


def _gated_bridge(*_args: Any, **_kwargs: Any) -> Any:
    """Stands in for the EE tier bridge as a below-Business tenant."""

    def _deny() -> None:
        raise OnyxError(
            OnyxErrorCode.FEATURE_NOT_AVAILABLE,
            "Multiple enabled SSO providers require the Business or Enterprise plan.",
        )

    return _deny


@pytest.mark.usefixtures("only_test_providers_enabled")
def test_second_enabled_provider_requires_business_tier(
    client: TestClient,
    provider_names: list[str],
) -> None:
    """Below Business, a second simultaneously enabled provider is blocked
    while single-provider management stays fully allowed: toggling the only
    provider works, and a second create passes once the first is disabled."""
    first_name = _new_provider_name()
    first_response = client.post(
        "/admin/sso/provider",
        json=_build_oidc_request(first_name, "first-secret"),
    )
    assert first_response.status_code == 200
    provider_names.append(first_name)
    first_id = first_response.json()["id"]

    with patch(
        "onyx.server.manage.sso.api.fetch_ee_implementation_or_noop",
        _gated_bridge,
    ):
        second_name = _new_provider_name()
        gated_create = client.post(
            "/admin/sso/provider",
            json=_build_oidc_request(second_name, "second-secret"),
        )
        assert (
            gated_create.status_code == OnyxErrorCode.FEATURE_NOT_AVAILABLE.status_code
        )
        assert (
            gated_create.json()["error_code"]
            == OnyxErrorCode.FEATURE_NOT_AVAILABLE.code
        )

        disable_first = client.post(
            f"/admin/sso/provider/{first_id}/enabled",
            json={"enabled": False},
        )
        assert disable_first.status_code == 200

        reenable_first = client.post(
            f"/admin/sso/provider/{first_id}/enabled",
            json={"enabled": True},
        )
        assert reenable_first.status_code == 200

        disable_again = client.post(
            f"/admin/sso/provider/{first_id}/enabled",
            json={"enabled": False},
        )
        assert disable_again.status_code == 200

        allowed_create = client.post(
            "/admin/sso/provider",
            json=_build_oidc_request(second_name, "second-secret"),
        )
        assert allowed_create.status_code == 200
        provider_names.append(second_name)

        gated_reenable = client.post(
            f"/admin/sso/provider/{first_id}/enabled",
            json={"enabled": True},
        )
        assert (
            gated_reenable.status_code
            == OnyxErrorCode.FEATURE_NOT_AVAILABLE.status_code
        )


@patch("onyx.db.sso_provider.MULTI_TENANT", True)
def test_multi_tenant_rejects_saml_and_admits_oauth(
    client: TestClient, provider_names: list[str]
) -> None:
    """Cloud cannot route a SAML assertion to a workspace, so SAML alone is
    refused. OAuth-shaped providers configure normally."""
    saml_response = client.post(
        "/admin/sso/provider",
        json=_build_saml_request(_new_provider_name("saml-test")),
    )
    assert saml_response.status_code == OnyxErrorCode.SINGLE_TENANT_ONLY.status_code
    assert saml_response.json()["error_code"] == OnyxErrorCode.SINGLE_TENANT_ONLY.code

    oidc_name = _new_provider_name()
    provider_names.append(oidc_name)
    oidc_response = client.post(
        "/admin/sso/provider",
        json=_build_oidc_request(oidc_name, "secret"),
    )
    assert oidc_response.status_code == 200

    types_response = client.get("/admin/sso/provider-type")
    assert types_response.status_code == 200
    assert types_response.json() == [
        SSOProviderType.GOOGLE_OAUTH.value,
        SSOProviderType.OIDC.value,
    ]


@pytest.mark.parametrize("domains", [[], [" "], ["", "  "]])
@patch("onyx.server.manage.sso.api.MULTI_TENANT", True)
def test_multi_tenant_requires_bounded_email_domains(
    client: TestClient, domains: list[str]
) -> None:
    """A list that stores empty turns the domain check off entirely. Blank
    entries are dropped on write, so they have to be judged normalized."""
    request = _build_oidc_request(_new_provider_name(), "secret")
    request["allowed_email_domains"] = domains

    response = client.post("/admin/sso/provider", json=request)
    assert response.status_code == OnyxErrorCode.INVALID_INPUT.status_code


@pytest.mark.parametrize(
    "domain", ["company a.com", "notadomain", "-bad.com", "bad_.com"]
)
@patch("onyx.server.manage.sso.api.MULTI_TENANT", True)
def test_multi_tenant_rejects_malformed_email_domains(
    client: TestClient, domain: str
) -> None:
    """A syntactically invalid domain would persist and route nowhere, then fail
    only later when verification tries to email it, so it is rejected at save."""
    request = _build_oidc_request(_new_provider_name(), "secret")
    request["allowed_email_domains"] = [domain]

    response = client.post("/admin/sso/provider", json=request)
    assert response.status_code == OnyxErrorCode.INVALID_INPUT.status_code


def test_single_tenant_allows_unbounded_email_domains(
    client: TestClient, provider_names: list[str]
) -> None:
    name = _new_provider_name()
    provider_names.append(name)
    request = _build_oidc_request(name, "secret")
    request["allowed_email_domains"] = []

    assert client.post("/admin/sso/provider", json=request).status_code == 200


def test_single_tenant_offers_every_provider_type(client: TestClient) -> None:
    types_response = client.get("/admin/sso/provider-type")
    assert types_response.status_code == 200
    assert SSOProviderType.SAML.value in types_response.json()
