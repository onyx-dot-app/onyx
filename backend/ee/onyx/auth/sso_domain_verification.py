"""Prove a workspace controls an email domain by publishing a DNS TXT record.

Domain routing auto-provisions strangers on a domain, so a workspace must show
it owns the domain first. Only whoever controls the domain's DNS can publish the
record we look for, so finding it is that proof. Verifying flips the catalog row
that lets the domain route. A scheduled re-check drops routing if the record
later disappears.
"""

import hashlib
import hmac

import dns.resolver
from dns.exception import DNSException

from ee.onyx.db.tenant_sso_domain import (
    is_claimed_domain,
    list_login_domains,
    mark_domain_unverified,
    mark_domain_verified,
)
from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.db.sso_provider import is_valid_email_domain
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Published under the claimed domain at this host, kept off the apex so it never
# collides with the domain's SPF or other TXT records.
VERIFICATION_HOST = "_onyx-verification"
_VALUE_PREFIX = "onyx-verify="
# Bounds a slow or unreachable resolver so it can't tie up the request.
_DNS_TIMEOUT_SECONDS = 5.0


def _domain_token(tenant_id: str, domain: str) -> str:
    """A stable per-(workspace, domain) token. Bound to the workspace so one
    tenant's published record cannot verify another's claim, and unguessable
    without USER_AUTH_SECRET so an attacker cannot forge a record for a domain
    they do not control."""
    message = f"sso-domain:{tenant_id}:{domain}".encode()
    digest = hmac.new(USER_AUTH_SECRET.encode(), message, hashlib.sha256)
    return digest.hexdigest()[:32]


def verification_record(tenant_id: str, domain: str) -> tuple[str, str]:
    """(host, value) of the TXT record the admin publishes to prove control."""
    domain = domain.strip().lower()
    host = f"{VERIFICATION_HOST}.{domain}"
    return host, f"{_VALUE_PREFIX}{_domain_token(tenant_id, domain)}"


def _txt_proof_matches(host: str, expected: str) -> bool | None:
    """Whether `expected` is among the host's TXT answers. None on a transient
    resolver failure, where the record's presence is unknown, so callers can
    tell a definitive miss (NXDOMAIN, no TXT) from a resolver blip."""
    resolver = dns.resolver.Resolver()
    resolver.timeout = _DNS_TIMEOUT_SECONDS
    resolver.lifetime = _DNS_TIMEOUT_SECONDS
    try:
        answers = resolver.resolve(host, "TXT")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False
    except DNSException:
        return None
    # A TXT record is one or more quoted chunks, joined before matching.
    return any(
        hmac.compare_digest(
            b"".join(record.strings).decode(errors="ignore").strip(), expected
        )
        for record in answers
    )


def verify_domain_via_dns(tenant_id: str, domain: str) -> bool:
    """Resolve the TXT record and verify the domain on a match. Returns whether
    a matching record was found. A miss is expected while DNS is still
    propagating."""
    domain = domain.strip().lower()
    if not is_valid_email_domain(domain):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "That is not a valid email domain."
        )
    if not is_claimed_domain(tenant_id, domain):
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "Save the provider with this domain before verifying it.",
        )

    host, expected = verification_record(tenant_id, domain)
    if _txt_proof_matches(host, expected):
        mark_domain_verified(tenant_id, domain)
        return True
    return False


def _proof_still_present(tenant_id: str, domain: str) -> bool:
    """Re-resolve the TXT proof for an already-verified domain. Returns True when
    the proof is present, and also on a transient resolver failure, so routing is
    dropped only on a definitive miss (NXDOMAIN, no TXT, or a changed value),
    never a resolver blip."""
    domain = domain.strip().lower()
    host, expected = verification_record(tenant_id, domain)
    return _txt_proof_matches(host, expected) is not False


def revalidate_tenant_domains(tenant_id: str) -> None:
    """Re-resolve each verified domain's TXT proof and drop verification for any
    whose record is gone, so a domain the workspace no longer controls stops
    routing strangers into it."""
    for record in list_login_domains(tenant_id):
        if not record.verified:
            continue
        try:
            if _proof_still_present(tenant_id, record.domain):
                continue
            mark_domain_unverified(tenant_id, record.domain)
            logger.info(
                "Dropped SSO routing for %s: its TXT proof no longer resolves",
                record.domain,
            )
        except Exception:
            logger.exception("Failed to re-validate SSO domain %s", record.domain)
