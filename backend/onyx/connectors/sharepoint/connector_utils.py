from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_serializer

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.sharepoint_rest import SharepointPermissionReader
from onyx.connectors.models import ExternalAccess
from onyx.db.enums import HierarchyNodeType
from onyx.utils.url import SSRFException, validate_outbound_http_url
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)


class SharepointGroup(BaseModel):
    model_config = {"frozen": True}

    name: str
    login_name: str
    principal_type: int


class SharepointGroupExpansion(BaseModel):
    nested_groups: set[SharepointGroup]

    @field_serializer("nested_groups")
    def serialize_nested_groups(
        self, nested_groups: set[SharepointGroup]
    ) -> list[SharepointGroup]:
        return list(nested_groups)


class SharepointPermissionCache(BaseModel):
    group_expansions: dict[str, SharepointGroupExpansion] = Field(default_factory=dict)


def _noop_external_access(*args: Any, **kwargs: Any) -> ExternalAccess:  # noqa: ARG001
    return ExternalAccess.empty()


def get_sharepoint_external_access(
    reader: SharepointPermissionReader,
    site_url: str,
    permission_cache: SharepointPermissionCache,
    drive_item: DriveItemData | None = None,
    list_id: str | None = None,
    site_page: dict[str, Any] | None = None,
    add_prefix: bool = False,
    treat_sharing_link_as_public: bool = False,
) -> ExternalAccess:
    if drive_item and not list_id:
        raise ValueError("SharePoint permission lookup requires a list ID")

    get_external_access_func = fetch_versioned_implementation_with_fallback(
        "onyx.external_permissions.sharepoint.permission_utils",
        "get_external_access_from_sharepoint",
        fallback=_noop_external_access,
    )

    return get_external_access_func(
        reader,
        site_url,
        list_id,
        drive_item,
        site_page,
        add_prefix,
        treat_sharing_link_as_public,
        permission_cache,
    )


def get_sharepoint_hierarchy_node_external_access(
    reader: SharepointPermissionReader,
    site_url: str,
    permission_cache: SharepointPermissionCache,
    node_type: HierarchyNodeType,
    list_id: str | None = None,
    folder_server_relative_path: str | None = None,
) -> ExternalAccess:
    if node_type == HierarchyNodeType.DRIVE and not list_id:
        raise ValueError("SharePoint permission lookup requires a list ID")

    get_external_access_func = fetch_versioned_implementation_with_fallback(
        "onyx.external_permissions.sharepoint.permission_utils",
        "get_hierarchy_node_external_access_from_sharepoint",
        fallback=_noop_external_access,
    )
    return get_external_access_func(
        reader,
        site_url,
        node_type,
        list_id,
        folder_server_relative_path,
        permission_cache,
    )


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


def validate_content_types(
    include_site_documents: bool, include_site_pages: bool
) -> None:
    if not include_site_documents and not include_site_pages:
        raise ConnectorValidationError(
            "At least one content type must be enabled. Turn on 'Index Documents' "
            "or 'Index ASPX Sites' (or both)."
        )


def is_site_url_well_formed(site_url: str) -> bool:
    """A full SharePoint or OneDrive site URL: https and a site path."""
    return site_url.startswith("https://") and (
        "/sites/" in site_url or "/teams/" in site_url or "/personal/" in site_url
    )


def validate_site_url(
    site_url: str, sharepoint_domain_suffix: str, tenant_domain: str | None
) -> None:
    """A full site URL, safe to request, on the tenant's host."""
    if not is_site_url_well_formed(site_url):
        raise ConnectorValidationError(
            f"`{site_url}` is not a full SharePoint or OneDrive site URL "
            "(https://tenant.sharepoint.com/sites/name or /teams/name, "
            "https://tenant-my.sharepoint.com/personal/name)."
        )
    try:
        validate_outbound_http_url(site_url, https_only=True)
    except (SSRFException, ValueError) as e:
        raise ConnectorValidationError(f"Invalid site URL '{site_url}': {e}") from e
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
        raise ConnectorValidationError(
            f"Site URL '{site_url}' must be on the '{suffix}' domain."
        )
    if tenant_domain is None:
        return
    expected = _expected_site_hostnames(tenant_domain, sharepoint_domain_suffix)
    if hostname not in expected:
        raise ConnectorValidationError(
            f"Site URL '{site_url}' is not on this tenant's SharePoint host "
            f"(expected one of: {', '.join(sorted(expected))})."
        )
