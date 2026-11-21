from urllib.parse import urlsplit

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.sharepoint.config import is_site_url_well_formed
from onyx.server.security.models import connector_ssrf_enforced
from onyx.server.security.store import get_security_settings
from onyx.utils.url import SSRFException, validate_outbound_http_url

# OneDrive sites live on '<tenant>-my.<suffix>' instead of '<tenant>.<suffix>'.
ONEDRIVE_HOST_SUFFIX = "-my"


def tenant_domain_from_site_urls(site_urls: list[str]) -> str | None:
    """The first label of a site hostname, e.g. "contoso" for
    https://contoso.sharepoint.com/sites/eng. None when no URL parses."""
    for site_url in site_urls:
        try:
            hostname = urlsplit(site_url.strip()).hostname
        except ValueError:
            continue
        if not hostname:
            continue
        tenant = hostname.split(".")[0]
        if tenant:
            return tenant
    return None


def _expected_site_hostnames(
    tenant_domain: str, sharepoint_domain_suffix: str
) -> set[str]:
    """The hosts the REST token is valid for. OneDrive lives on the ``-my``
    sibling of the tenant host, so both forms of the tenant label are
    accepted."""
    tenant = tenant_domain.lower().removesuffix(ONEDRIVE_HOST_SUFFIX)
    suffix = sharepoint_domain_suffix.lower()
    return {f"{tenant}.{suffix}", f"{tenant}{ONEDRIVE_HOST_SUFFIX}.{suffix}"}


class SiteUrlFormatError(ConnectorValidationError):
    """A site URL that is not https with a site path."""


class SiteUrlBlockedError(ConnectorValidationError):
    """A site URL the outbound URL guard rejects."""


class SiteUrlHostError(ConnectorValidationError):
    """A site URL off the cloud's suffix or the tenant's host."""


def validate_content_types(
    include_site_documents: bool, include_site_pages: bool
) -> None:
    if not include_site_documents and not include_site_pages:
        raise ConnectorValidationError(
            "At least one content type must be enabled. Turn on 'Index Documents' "
            "or 'Index ASPX Sites' (or both)."
        )


def validate_site_url(
    site_url: str, sharepoint_domain_suffix: str, tenant_domain: str | None
) -> None:
    """A full site URL, on the tenant's host, that the shared connector SSRF
    policy lets the server call."""
    if not is_site_url_well_formed(site_url):
        raise SiteUrlFormatError(
            f"`{site_url}` is not a full SharePoint or OneDrive site URL "
            "(https://tenant.sharepoint.com/sites/name or /teams/name, "
            "https://tenant-my.sharepoint.com/personal/name)."
        )
    enforced: bool = connector_ssrf_enforced(
        get_security_settings().ssrf_protection_level
    )
    try:
        validate_outbound_http_url(
            site_url,
            https_only=True,
            allow_private_network=not enforced,
            block_link_local_only=not enforced,
        )
    except (SSRFException, ValueError) as e:
        raise SiteUrlBlockedError(f"Invalid site URL '{site_url}': {e}") from e
    validate_site_url_host(site_url, sharepoint_domain_suffix, tenant_domain)


def validate_site_url_host(
    site_url: str, sharepoint_domain_suffix: str, tenant_domain: str | None
) -> None:
    """Reject a site URL the REST token must not be sent to.

    The token is minted for one tenant, so a host like
    'tenant.attacker.example/sites/x' would leak it to the attacker, and
    another tenant under the same cloud suffix would receive a token it has
    no claim to. Without a tenant domain only the suffix is checked.
    """
    suffix = sharepoint_domain_suffix.lower()
    hostname = (urlsplit(site_url).hostname or "").lower()
    if hostname != suffix and not hostname.endswith(f".{suffix}"):
        raise SiteUrlHostError(
            f"Site URL '{site_url}' must be on the '{suffix}' domain."
        )
    if tenant_domain is None:
        return
    expected = _expected_site_hostnames(tenant_domain, sharepoint_domain_suffix)
    if hostname not in expected:
        raise SiteUrlHostError(
            f"Site URL '{site_url}' is not on this tenant's SharePoint host "
            f"(expected one of: {', '.join(sorted(expected))})."
        )
