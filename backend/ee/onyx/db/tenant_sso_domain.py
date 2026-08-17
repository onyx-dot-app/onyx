"""Email-domain routing for the cloud login page.

Someone signing in for the first time has no account and no membership row, so
nothing about them names a workspace. Their address domain does, once an admin
has declared it on a provider and proven the workspace controls it. Those
declarations live in per-tenant tables that cannot be read before a workspace is
known, so they are projected here, into the one catalog every login request can
reach.

A domain only routes once it is verified. Declaring a domain records a pending
claim. The workspace proves control by publishing a DNS TXT record for the
domain. Until then the domain routes nowhere, so a workspace cannot pull
addresses on a domain it has not shown it owns. Several workspaces may hold the
same domain pending, but only one can verify it.
"""

import datetime
from typing import NamedTuple

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from onyx.db.engine.sql_engine import get_catalog_session, get_session_with_tenant
from onyx.db.models import TenantSSODomain
from onyx.db.sso_provider import enabled_provider_domains
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def _email_domain(email: str) -> str | None:
    """The normalized domain of an address, or None when it has none."""
    _, _, domain = email.rpartition("@")
    return domain.strip().lower() or None


def lookup_tenant_id_for_email_domain(email: str) -> str | None:
    """Workspace an address routes to on its domain alone, for someone who has
    no account yet. Only verified domains route."""
    if not MULTI_TENANT:
        return None

    domain = _email_domain(email)
    if not domain:
        return None

    with get_catalog_session() as db_session:
        return db_session.scalar(
            select(TenantSSODomain.tenant_id).where(
                TenantSSODomain.domain == domain,
                TenantSSODomain.verified_at.isnot(None),
            )
        )


def is_email_domain_verified(tenant_id: str, email: str) -> bool:
    """Whether this workspace has proven control of the address's domain.

    A tenant-controlled IdP can assert any address, so a login through one is
    trusted to provision or move a membership only for a domain the workspace
    has verified. An address whose domain this workspace has not verified
    returns False.
    """
    if not MULTI_TENANT:
        return False

    domain = _email_domain(email)
    if not domain:
        return False

    with get_catalog_session() as db_session:
        return (
            db_session.scalar(
                select(TenantSSODomain.tenant_id).where(
                    TenantSSODomain.tenant_id == tenant_id,
                    TenantSSODomain.domain == domain,
                    TenantSSODomain.verified_at.isnot(None),
                )
            )
            is not None
        )


def claim_email_domains(tenant_id: str, domains: list[str]) -> None:
    """Record this workspace's pending claim on the domains it declares, and drop
    any it no longer claims.

    A claim does not route until verified. A domain that stays claimed keeps its
    verification, so re-saving a provider never un-verifies a domain.
    """
    if not MULTI_TENANT:
        return

    wanted = {domain.strip().lower() for domain in domains if domain.strip()}

    with get_catalog_session() as db_session:
        held = set(
            db_session.scalars(
                select(TenantSSODomain.domain).where(
                    TenantSSODomain.tenant_id == tenant_id
                )
            ).all()
        )

        released = held - wanted
        if released:
            db_session.execute(
                delete(TenantSSODomain).where(
                    TenantSSODomain.tenant_id == tenant_id,
                    TenantSSODomain.domain.in_(released),
                )
            )

        for domain in wanted - held:
            db_session.add(TenantSSODomain(tenant_id=tenant_id, domain=domain))

        db_session.commit()


class LoginDomainRecord(NamedTuple):
    domain: str
    verified: bool


def list_login_domains(tenant_id: str) -> list[LoginDomainRecord]:
    """The workspace's claimed domains and whether each is verified."""
    if not MULTI_TENANT:
        return []

    with get_catalog_session() as db_session:
        rows = db_session.execute(
            select(TenantSSODomain.domain, TenantSSODomain.verified_at).where(
                TenantSSODomain.tenant_id == tenant_id
            )
        ).all()

    return [
        LoginDomainRecord(domain=domain, verified=verified_at is not None)
        for domain, verified_at in rows
    ]


def is_claimed_domain(tenant_id: str, domain: str) -> bool:
    if not MULTI_TENANT:
        return False
    with get_catalog_session() as db_session:
        return db_session.get(TenantSSODomain, (tenant_id, domain)) is not None


def mark_domain_verified(tenant_id: str, domain: str) -> None:
    """Flag a claimed domain verified so it starts routing. Raises if another
    workspace already verified it, which the partial-unique index enforces."""
    if not MULTI_TENANT:
        return

    with get_catalog_session() as db_session:
        row = db_session.get(TenantSSODomain, (tenant_id, domain))
        if row is None:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND, "This workspace has not claimed that domain."
            )
        if row.verified_at is not None:
            return
        row.verified_at = datetime.datetime.now(datetime.timezone.utc)
        try:
            db_session.commit()
        except IntegrityError as e:
            db_session.rollback()
            raise OnyxError(
                OnyxErrorCode.DUPLICATE_RESOURCE,
                "Another workspace has already verified this domain.",
            ) from e


def mark_domain_unverified(tenant_id: str, domain: str) -> None:
    """Drop a domain's verification so it stops routing. The scheduled re-check
    calls this when the domain's TXT proof is no longer resolvable."""
    if not MULTI_TENANT:
        return

    with get_catalog_session() as db_session:
        row = db_session.get(TenantSSODomain, (tenant_id, domain))
        if row is None or row.verified_at is None:
            return
        row.verified_at = None
        db_session.commit()


def reproject_tenant_login_domains(tenant_id: str) -> None:
    """Re-project one workspace's enabled-provider domains into the catalog, so a
    disable or a domain removal stops routing even if the on-save projection
    failed. A domain that stays claimed keeps its verification."""
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        domains = enabled_provider_domains(db_session)
    claim_email_domains(tenant_id, sorted(domains))
