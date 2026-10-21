from typing import Annotated

from pydantic import field_validator

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    SHAREPOINT_EXHAUSTIVE_AD_ENUMERATION,
)
from onyx.connectors.connector_config import ConnectorConfig, field_format_error
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeExclude,
    ScopeInclude,
    ScopeToggle,
)
from onyx.connectors.microsoft_utils.config import (
    DEFAULT_SHAREPOINT_DOMAIN_SUFFIX,
    MicrosoftCloudBinding,
)

SITE_URL_FORMAT_ERROR = (
    "Enter a full site URL, e.g. https://acme.sharepoint.com/sites/hr."
)

_COSMETIC = FieldPolicy(FieldClass.COSMETIC)
_CONTENT_TYPE_TOGGLE = FieldPolicy(
    FieldClass.SCOPE, scope=ScopeToggle(widens_when=True)
)


def is_site_url_well_formed(site_url: str) -> bool:
    """A full SharePoint or OneDrive site URL: https and a site path."""
    return site_url.startswith("https://") and (
        "/sites/" in site_url or "/teams/" in site_url or "/personal/" in site_url
    )


class SharepointCredentialBinding(MicrosoftCloudBinding):
    # Ignored: the connector uses the suffix of the cloud graph_api_host selects.
    sharepoint_domain_suffix: Annotated[str, _COSMETIC] = (
        DEFAULT_SHAREPOINT_DOMAIN_SUFFIX
    )


class SharepointConnectorConfig(SharepointCredentialBinding, ConnectorConfig):
    batch_size: Annotated[int, _COSMETIC] = INDEX_BATCH_SIZE
    sites: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    excluded_sites: Annotated[
        list[str] | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = None
    excluded_paths: Annotated[
        list[str] | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = None
    include_site_pages: Annotated[bool, _CONTENT_TYPE_TOGGLE] = True
    include_site_documents: Annotated[bool, _CONTENT_TYPE_TOGGLE] = True
    # Changes the access list of indexed documents.
    treat_sharing_link_as_public: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = (
        False
    )
    # Read only by the EE group sync, not by indexing.
    exhaustive_ad_enumeration: Annotated[bool, _COSMETIC] = (
        SHAREPOINT_EXHAUSTIVE_AD_ENUMERATION
    )

    # Indexing validates every entry, blanks included. The host and the
    # outbound URL guard depend on the cloud and DNS, so the checks keep them.
    @field_validator("sites")
    @classmethod
    def _sites_are_full_site_urls(cls, value: list[str] | None) -> list[str] | None:
        if any(not is_site_url_well_formed(site_url) for site_url in value or []):
            raise field_format_error(SITE_URL_FORMAT_ERROR)
        return value
