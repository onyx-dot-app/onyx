from typing import Any

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.sso_url_guard import UnsafeSSOUrl, validate_idp_url
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission, SSOProviderType
from onyx.db.models import SSOProvider, User
from onyx.db.sso_provider import (
    create_sso_provider,
    enabled_provider_domains,
    fetch_sso_providers,
    is_valid_email_domain,
    normalize_email_domains,
    set_sso_provider_enabled,
    sso_provider_type_supported,
    supported_sso_provider_types,
    update_sso_provider,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.get_state import invalidate_sso_provider_options_cache
from onyx.server.manage.sso.models import (
    SSODomainRecordsRequest,
    SSODomainVerifyRequest,
    SSOLoginDomainsResponse,
    SSOLoginDomainStatus,
    SSOProviderCreateRequest,
    SSOProviderEnabledRequest,
    SSOProviderResponse,
    SSOProviderUpdateRequest,
)
from onyx.server.security.store import (
    load_effective_uncached,
    security_settings_write_lock,
)
from onyx.utils.encryption import reject_masked_credentials, restore_masked_credentials
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def _reject_unsupported_provider_type(provider_type: SSOProviderType) -> None:
    if not sso_provider_type_supported(provider_type):
        raise OnyxError(
            OnyxErrorCode.SINGLE_TENANT_ONLY,
            f"{provider_type.value} providers are not available on this deployment.",
        )


def _validate_cloud_email_domains(allowed_email_domains: list[str] | None) -> None:
    """On cloud the domain list is both the seat boundary and a routing key, so
    it must be non-empty and every entry a valid hostname. A malformed domain
    would otherwise persist and fail only later, at DNS verification. Judged
    after normalization, which drops blanks. Single-tenant leaves the list
    optional and unrouted, so it skips both checks."""
    if not MULTI_TENANT or allowed_email_domains is None:
        return
    normalized = normalize_email_domains(allowed_email_domains)
    if not normalized:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "List the email domains this provider may sign in. Leaving it empty "
            "would let any address its identity provider asserts join the workspace.",
        )
    invalid = [domain for domain in normalized if not is_valid_email_domain(domain)]
    if invalid:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"These are not valid email domains: {', '.join(invalid)}.",
        )


def _sync_login_domain_routing(db_session: Session) -> None:
    """Project every enabled provider's domains into the shared catalog, which
    is the only place the login page can read before a workspace is known.
    Recomputed from the rows rather than diffed, so a disable or a domain
    removal stops routing without its own bookkeeping."""
    # The provider commit is the source of truth, so this whole projection is
    # best-effort: any failure reprojecting the catalog must not fail a saved
    # provider, and the next save re-syncs.
    try:
        claimed = enabled_provider_domains(db_session)
        fetch_ee_implementation_or_noop(
            "onyx.db.tenant_sso_domain", "claim_email_domains", None
        )(get_current_tenant_id(), sorted(claimed))
    except Exception:
        logger.exception("Failed to project SSO login-domain routing")


def _reject_unfetchable_idp_url(config: dict[str, Any]) -> None:
    """Fails the write rather than the first login, so an admin who typo'd a
    host hears about it here."""
    discovery_url = config.get("openid_config_url")
    if not isinstance(discovery_url, str) or not discovery_url:
        return
    try:
        validate_idp_url(discovery_url, field="openid_config_url")
    except UnsafeSSOUrl as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e


admin_router = APIRouter(prefix="/admin/sso")


def _require_business_tier_for_additional_enabled_provider(
    db_session: Session, exclude_provider_id: int | None = None
) -> None:
    """Enabling providers beyond the first requires Business or above. One
    enabled provider works at every tier, so single-provider setup stays
    free."""
    enabled = fetch_sso_providers(db_session, enabled_only=True)
    if any(provider.id != exclude_provider_id for provider in enabled):
        fetch_ee_implementation_or_noop(
            "onyx.utils.tier",
            "require_business_tier_for_multi_sso",
            noop_return_value=None,
        )()


def _fetch_sso_provider_or_raise(db_session: Session, provider_id: int) -> SSOProvider:
    provider = db_session.get(SSOProvider, provider_id)
    if provider is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"SSO provider {provider_id} does not exist",
        )
    return provider


@admin_router.get("/provider-type")
def list_supported_sso_provider_types(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> list[SSOProviderType]:
    """Provider types this deployment can serve, so the admin UI never offers a
    type the create endpoint would reject."""
    return supported_sso_provider_types()


@admin_router.get("/provider")
def list_sso_providers(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[SSOProviderResponse]:
    return [
        SSOProviderResponse.from_model(provider, WEB_DOMAIN)
        for provider in fetch_sso_providers(db_session, enabled_only=False)
    ]


@admin_router.post("/provider")
def create_sso_provider_endpoint(
    request: SSOProviderCreateRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SSOProviderResponse:
    _reject_unsupported_provider_type(request.provider_type)
    _reject_unfetchable_idp_url(request.config)
    _validate_cloud_email_domains(request.allowed_email_domains)
    # New providers are created enabled, so an existing enabled provider
    # makes this a multi-SSO create.
    _require_business_tier_for_additional_enabled_provider(db_session)

    try:
        reject_masked_credentials(request.config)
        provider = create_sso_provider(
            db_session=db_session,
            name=request.name,
            display_name=request.display_name,
            provider_type=request.provider_type,
            config=request.config,
            allowed_email_domains=request.allowed_email_domains,
        )
    except IntegrityError as e:
        db_session.rollback()
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            f"SSO provider with name {request.name} already exists",
        ) from e
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e

    _sync_login_domain_routing(db_session)
    invalidate_sso_provider_options_cache()
    return SSOProviderResponse.from_model(provider, WEB_DOMAIN)


@admin_router.patch("/provider/{provider_id}")
def update_sso_provider_endpoint(
    provider_id: int,
    request: SSOProviderUpdateRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SSOProviderResponse:
    provider = _fetch_sso_provider_or_raise(db_session, provider_id)
    _validate_cloud_email_domains(request.allowed_email_domains)

    try:
        merged_config: dict[str, Any] | None = None
        if request.config is not None:
            stored_config = (
                provider.config.get_value(apply_mask=False) if provider.config else {}
            )
            # Overlay only the keys the caller sent so a partial payload can't
            # drop stored config. Masked placeholders restore the stored value
            # in place.
            merged_config = {
                **stored_config,
                **restore_masked_credentials(request.config, stored_config),
            }
            reject_masked_credentials(merged_config)
            _reject_unfetchable_idp_url(merged_config)
        updated_provider = update_sso_provider(
            db_session=db_session,
            provider_id=provider_id,
            display_name=request.display_name,
            config=merged_config,
            allowed_email_domains=request.allowed_email_domains,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e

    _sync_login_domain_routing(db_session)
    invalidate_sso_provider_options_cache()
    return SSOProviderResponse.from_model(updated_provider, WEB_DOMAIN)


@admin_router.post("/provider/{provider_id}/enabled")
def set_sso_provider_enabled_endpoint(
    provider_id: int,
    request: SSOProviderEnabledRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SSOProviderResponse:
    provider_to_toggle = _fetch_sso_provider_or_raise(db_session, provider_id)
    if request.enabled:
        _reject_unsupported_provider_type(provider_to_toggle.provider_type)
        # Catches a row stored before the bound existed, which the write paths
        # never revisit.
        _validate_cloud_email_domains(provider_to_toggle.allowed_email_domains)
        _require_business_tier_for_additional_enabled_provider(
            db_session, exclude_provider_id=provider_id
        )
        provider = set_sso_provider_enabled(
            db_session=db_session,
            provider_id=provider_id,
            enabled=True,
        )
    else:
        # Both lockout guards run under the shared write lock on fresh state.
        with security_settings_write_lock():
            if not load_effective_uncached().password_auth_enabled and not any(
                other.id != provider_id
                for other in fetch_sso_providers(db_session, enabled_only=True)
            ):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "Re-enable password login before disabling the last SSO "
                    "provider, otherwise no one can sign in.",
                )
            provider = set_sso_provider_enabled(
                db_session=db_session,
                provider_id=provider_id,
                enabled=False,
            )

    _sync_login_domain_routing(db_session)
    invalidate_sso_provider_options_cache()
    return SSOProviderResponse.from_model(provider, WEB_DOMAIN)


def _list_login_domains(tenant_id: str) -> list[Any]:
    return fetch_ee_implementation_or_noop(
        "onyx.db.tenant_sso_domain", "list_login_domains", lambda _tenant_id: []
    )(tenant_id)


def _build_statuses(
    tenant_id: str, domains: list[str], verified: set[str], claimed: set[str]
) -> SSOLoginDomainsResponse:
    """Pair each domain with its status. A verified domain routes and needs no
    record. A pending one carries the TXT record to publish."""
    verification_record = fetch_ee_implementation_or_noop(
        "onyx.auth.sso_domain_verification",
        "verification_record",
        lambda _tenant_id, _domain: (None, None),
    )

    def _status(domain: str) -> SSOLoginDomainStatus:
        if domain in verified:
            return SSOLoginDomainStatus(domain=domain, verified=True, claimed=True)
        host, value = verification_record(tenant_id, domain)
        return SSOLoginDomainStatus(
            domain=domain,
            verified=False,
            claimed=domain in claimed,
            record_host=host,
            record_value=value,
        )

    return SSOLoginDomainsResponse(domains=[_status(domain) for domain in domains])


def _login_domains_response(tenant_id: str) -> SSOLoginDomainsResponse:
    records = _list_login_domains(tenant_id)
    domains = [record.domain for record in records]
    verified = {record.domain for record in records if record.verified}
    return _build_statuses(tenant_id, domains, verified, set(domains))


def _domain_statuses(tenant_id: str, domains: list[str]) -> SSOLoginDomainsResponse:
    """Statuses for a specific set of domains, claimed or not, so verification can
    be shown before the provider is saved. Domains are normalized so a mixed-case
    entry matches the lowercased catalog."""
    normalized = [domain.strip().lower() for domain in domains]
    records = _list_login_domains(tenant_id)
    verified = {record.domain for record in records if record.verified}
    return _build_statuses(
        tenant_id, normalized, verified, {record.domain for record in records}
    )


@admin_router.post("/domain/records")
def sso_domain_records_endpoint(
    payload: SSODomainRecordsRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> SSOLoginDomainsResponse:
    """The TXT record and status for the domains an admin is configuring, so
    verification can be shown before the provider is saved."""
    if not MULTI_TENANT:
        return SSOLoginDomainsResponse(domains=[])
    return _domain_statuses(get_current_tenant_id(), payload.domains)


@admin_router.post("/domain/verify-dns")
async def verify_sso_domain_via_dns_endpoint(
    payload: SSODomainVerifyRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> SSOLoginDomainsResponse:
    if not MULTI_TENANT:
        raise OnyxError(OnyxErrorCode.SINGLE_TENANT_ONLY)

    tenant_id = get_current_tenant_id()
    # DNS resolution blocks, so keep it off the event loop.
    found = await run_in_threadpool(
        fetch_ee_implementation_or_noop(
            "onyx.auth.sso_domain_verification",
            "verify_domain_via_dns",
            lambda _tenant_id, _domain: False,
        ),
        tenant_id,
        payload.domain,
    )
    if not found:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "We couldn't find the TXT record yet. DNS can take up to an hour to "
            "update, then check again.",
        )
    invalidate_sso_provider_options_cache()
    return _login_domains_response(tenant_id)
