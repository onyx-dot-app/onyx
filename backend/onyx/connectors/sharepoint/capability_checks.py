"""Capability checks for the SharePoint connector.

The indexing checks register in ``registry.py``, the permission-sync checks in
the EE registry. Each check makes small probes (one page, one item, one group)
with the gateway operations the connector calls, on probe sites: the first few
configured sites that Graph finds, else the first few Graph lists.

The settings rules the connector's own validation applies (one content type
on, well-formed site URLs on the tenant's host) are checks too, since the
named checks replace that validation at creation.

"Find selected sites" and "Find selected libraries" are partial finds: when
some are missing they are INCOMPLETE, and the checks after them run on the
sites and libraries they found.
"""

from datetime import datetime
from typing import NoReturn

from pydantic import BaseModel

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
    form_config,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
    NothingToCheckError,
    UnexpectedValidationError,
    ValidationError,
)
from onyx.connectors.microsoft_utils.check_text import (
    ENTRA_GROUPS_DENIED_ROW,
    SHAREPOINT_API,
    format_date,
    grant_line,
)
from onyx.connectors.microsoft_utils.drive_delta import (
    DriveDeltaFetchResult,
    DriveDeltaItem,
    build_delta_start_url,
)
from onyx.connectors.microsoft_utils.drive_items import (
    DriveItemData,
    build_item_relative_path,
    is_path_excluded,
)
from onyx.connectors.microsoft_utils.entra import EntraGroup, EntraPage
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.microsoft_utils.graph_env import (
    MicrosoftGraphEnvironment,
    resolve_microsoft_environment,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError,
    MicrosoftGraphError,
    raise_for_auth_error,
    raise_for_graph_error,
)
from onyx.connectors.microsoft_utils.models import (
    MicrosoftAccountLabels,
    MicrosoftRowText,
    MicrosoftSignIn,
    SharepointPrincipal,
    SharepointRoleAssignment,
    SharepointSecurable,
    SharepointSecurableKind,
)
from onyx.connectors.microsoft_utils.sharepoint_principals import (
    SharepointPrincipalType,
    granting_members,
    is_public_login_name,
    resolve_group_id,
)
from onyx.connectors.microsoft_utils.sign_in import sign_in
from onyx.connectors.sharepoint import connector_utils
from onyx.connectors.sharepoint.config import SharepointConnectorConfig
from onyx.connectors.sharepoint.connector import (
    ONEDRIVE_HOST_MARKER,
    PERSONAL_SITE_URL_MARKER,
    DriveMetadataError,
    SiteDescriptor,
    SiteDrive,
    build_folder_server_relative_path,
    extract_site_descriptors,
    is_graph_invalid_request,
    is_site_excluded,
    select_site_drive,
    site_drive_from_graph,
)
from onyx.connectors.sharepoint.connector_utils import (
    SiteUrlBlockedError,
    SiteUrlFormatError,
    SiteUrlHostError,
    tenant_domain_from_site_urls,
    validate_content_types,
)
from onyx.connectors.sharepoint.models import (
    SharepointDrive,
    SitePagesPage,
    SiteUrlListing,
)
from onyx.connectors.sharepoint.source_operations import (
    GRAPH_API_VERSION,
    SharepointSourceOperations,
)
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.utils.logger import setup_logger

logger = setup_logger()

_DOCS_LINK: str = "https://docs.onyx.app/admins/connectors/official/sharepoint"
_PROBE_SITES: int = 5
# Listed sites the documents probe reads in turn for one file indexing would
# read. Tenants often list empty or demo sites first, in no stable order.
# Each site costs one library listing, so the whole first listing page (up to
# hundreds of sites) is too many.
_PROBE_SAMPLE_SITES: int = 20
# Libraries whose first delta page holds no indexable file before the probe
# stops, so a tenant of empty libraries cannot spend the check's budget.
_PROBE_LIBRARIES: int = 10
# The same bound for the documents probe, one library for each sample site.
_PROBE_SAMPLE_LIBRARIES: int = _PROBE_SAMPLE_SITES
# Site groups searched for an Entra group when the site names none directly,
# the way the sync expands site groups to find the Entra groups inside them.
_PROBE_SITE_GROUPS: int = 5
# One page each: a probe proves the read without walking a large permission
# list, site group or Entra group.
_PROBE_ROLE_ASSIGNMENTS: int = 100
_PROBE_SHARING_LINKS: int = 50
_PROBE_GROUP_MEMBERS: int = 50
_PROBE_NESTED_GROUPS: int = 50
# A delta page lists folders before files, so one row is rarely a file.
_PROBE_DELTA_PAGE_SIZE: int = 25
# A download probe reads one real file. A large one would spend the check's
# time budget on bytes the check learns nothing from.
_MAX_PROBE_DOWNLOAD_BYTES: int = 5 * 1024 * 1024
# The longest row line the card shows.
_MAX_LINE: int = 40
_LOCKED_STATUS: int = 423
_READ_REMEDIATION: str = (
    "Grant `Sites.Read.All` (application permission) and admin-consent it, or "
    "with `Sites.Selected` grant the app read access on each configured site."
)
_REST_REMEDIATION: str = (
    "Grant `Sites.FullControl.All` (application permission) and admin-consent "
    "it, or with `Sites.Selected` grant the app full control on each configured "
    "site."
)
_GROUPS_REMEDIATION: str = (
    "Grant `GroupMember.Read.All` (application permission) and admin-consent it."
)
_CERTIFICATE_REMEDIATION: str = (
    "Recreate the credential with Certificate Authentication, or turn permission "
    "sync off."
)
_SITE_SECURABLE: SharepointSecurable = SharepointSecurable(
    kind=SharepointSecurableKind.SITE
)
_ACCOUNT_LABELS: MicrosoftAccountLabels = MicrosoftAccountLabels.with_prefix(
    "SharePoint"
)
_READ_GRANT: str = grant_line("Sites.Read.All")
_REST_GRANT: str = grant_line("Sites.FullControl.All", SHAREPOINT_API)
_GROUPS_GRANT: str = grant_line("GroupMember.Read.All")
_RETRY_LINE: str = (
    "Re-run the checks. If it repeats, send the error details to support."
)
_LOCKED_LINE: str = "Check whether the site is locked or archived."

_SIGN_IN_CHECK_ID = "sharepoint_token_auth"
_SITES_VISIBLE_CHECK_ID = "sharepoint_sites_visible"
_CONFIGURED_SITES_CHECK_ID = "sharepoint_configured_sites"
_CONFIGURED_LIBRARIES_CHECK_ID = "sharepoint_configured_libraries"
_CERTIFICATE_CHECK_ID = "sharepoint_certificate_auth"
_GROUP_ENUMERATION_CHECK_ID = "sharepoint_entra_group_enumeration"
# The two site checks are alternatives: only one applies to a config.
_SITE_CHECK_IDS: tuple[str, ...] = (
    _SITES_VISIBLE_CHECK_ID,
    _CONFIGURED_SITES_CHECK_ID,
)
# check_id to the checks it runs after, in run order.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    _SITES_VISIBLE_CHECK_ID: (_SIGN_IN_CHECK_ID,),
    _CONFIGURED_SITES_CHECK_ID: (_SIGN_IN_CHECK_ID,),
    _CONFIGURED_LIBRARIES_CHECK_ID: (_CONFIGURED_SITES_CHECK_ID,),
    # The site checks too: the library check does not apply to site URLs
    # that name no library.
    "sharepoint_documents_read": (*_SITE_CHECK_IDS, _CONFIGURED_LIBRARIES_CHECK_ID),
    "sharepoint_site_pages_read": _SITE_CHECK_IDS,
    _CERTIFICATE_CHECK_ID: (_SIGN_IN_CHECK_ID,),
    "sharepoint_site_permissions_read": (_CERTIFICATE_CHECK_ID,),
    "sharepoint_site_group_members_read": (_CERTIFICATE_CHECK_ID,),
    "sharepoint_document_permissions_read": (_CERTIFICATE_CHECK_ID,),
    "sharepoint_page_permissions_read": (_CERTIFICATE_CHECK_ID,),
    _GROUP_ENUMERATION_CHECK_ID: (_SIGN_IN_CHECK_ID,),
    # The certificate too: both start from a site's SharePoint REST
    # permissions.
    "sharepoint_entra_group_members_read": (
        _GROUP_ENUMERATION_CHECK_ID,
        _CERTIFICATE_CHECK_ID,
    ),
    "sharepoint_entra_nested_groups_read": (
        _GROUP_ENUMERATION_CHECK_ID,
        _CERTIFICATE_CHECK_ID,
    ),
}


def _gateway(context: CapabilityCheckContext) -> SharepointSourceOperations:
    if not isinstance(context.source_operations, SharepointSourceOperations):
        raise TypeError("SharePoint checks need the SharePoint gateway.")
    return context.source_operations


def _config(context: CapabilityCheckContext) -> SharepointConnectorConfig:
    return form_config(context, SharepointConnectorConfig)


def _configured_sites(config: SharepointConnectorConfig) -> list[str]:
    """The raw entries, blanks included: indexing validates every one."""
    return list(config.sites or [])


def _excluded_patterns(config: SharepointConnectorConfig) -> list[str]:
    return [
        pattern.strip() for pattern in config.excluded_sites or [] if pattern.strip()
    ]


def _descriptors(config: SharepointConnectorConfig) -> list[SiteDescriptor]:
    """The configured sites indexing reads: parsed, and the excluded ones
    left out."""
    patterns: list[str] = _excluded_patterns(config)
    return [
        site
        for site in extract_site_descriptors(_configured_sites(config))
        if not is_site_excluded(site.url, patterns)
    ]


def _graph_api_base(config: SharepointConnectorConfig) -> str:
    environment: MicrosoftGraphEnvironment = resolve_microsoft_environment(
        config.graph_api_host, config.authority_host
    )
    return f"{environment.graph_host}/{GRAPH_API_VERSION}"


# --- Row text ---


def _line(prefix: str, name: str) -> str:
    """``prefix`` and ``name``, with the name cut to fit the row."""
    room: int = _MAX_LINE - len(prefix)
    return prefix + (name if len(name) <= room else name[: room - 1] + "…")


def _site_name(site_url: str) -> str:
    """The short name of a site, the last part of its URL."""
    return site_url.rstrip("/").rsplit("/", 1)[-1]


def _counted(count: int, noun: str, plural: str) -> str:
    return f"{count} {noun if count == 1 else plural}"


def _row(summary: str, description: str) -> MicrosoftRowText:
    return MicrosoftRowText(summary=summary, description=description)


def _site_denied_row(site_url: str) -> MicrosoftRowText:
    return _row(
        _line("No read access to ", _site_name(site_url)),
        f"The app has no read grant on {site_url}.\n{_READ_GRANT}",
    )


def _site_not_found_row(site_url: str) -> MicrosoftRowText:
    return _row(
        _line("Site not found: ", _site_name(site_url)),
        f"Microsoft found no site at {site_url}.\nCorrect or remove the URL in Sites.",
    )


def _site_invalid_row(site_url: str) -> MicrosoftRowText:
    return _row(
        _line("Site URL not valid: ", _site_name(site_url)),
        f"Microsoft refused {site_url}.\nUse a site URL on this tenant in Sites.",
    )


def _site_permissions_denied_row(site_url: str) -> MicrosoftRowText:
    return _row(
        _line("No access to permissions of ", _site_name(site_url)),
        f"The app cannot read who has access to {site_url}.\n{_REST_GRANT}",
    )


def _library_not_found_row(library: str) -> MicrosoftRowText:
    return _row(
        _line("Library not found: ", library),
        "The site has no library with this name in its URL.\nCopy the library URL "
        "from the browser into Sites.",
    )


def _library_ambiguous_row(site_url: str) -> MicrosoftRowText:
    return _row(
        _line("Library name is ambiguous in ", _site_name(site_url)),
        "More than one library matches the library part of this site URL.\nUse "
        "the URL of the one library you want in Sites.",
    )


def _library_unreadable_row(library: str) -> MicrosoftRowText:
    return _row(
        _line("Library not readable: ", library),
        f"Microsoft refused the file listing of this library.\n{_RETRY_LINE}",
    )


_UNEXPECTED_LIBRARY_ROW = _row(
    "Unexpected library data from Microsoft",
    f"Microsoft listed a library without the fields indexing needs.\n{_RETRY_LINE}",
)
_REST_TOKEN_ROW = _row(
    "No token for the SharePoint host",
    "Microsoft did not issue a token for this tenant's SharePoint host.\nCheck "
    "the AADSTS code in the error details and fix what it names.",
)
_NO_SITES_ROW = _row(
    "No sites to test",
    "Every site in scope is excluded.\nCheck Sites and Excluded Sites.",
)
_NO_LIBRARIES_ROW = _row(
    "No libraries in scope",
    "No library was found on the sites in scope.\nCheck Sites and Excluded Sites.",
)
_NO_PAGES_ROW = _row(
    "No site pages in scope", "The sites in scope have no modern pages."
)
_LIST_SITES_DENIED_ROW = _row(
    "No permission to list sites",
    "With no site selected, the connector must list every site.\nGrant "
    "`Sites.Read.All`, or select the sites to index in Sites.",
)
_FILE_GONE_ROW = _row(
    "Sample file disappeared",
    "The file was deleted or moved between the listing and the download.\nRe-run "
    "the checks.",
)


def _raise_row(
    error_class: type[ValidationError], message: str, row: MicrosoftRowText
) -> NoReturn:
    raise error_class(message, summary=row.summary, description=row.description)


def _raise_for_read_error(
    error: MicrosoftGraphError,
    denied: str,
    missing: str,
    *,
    denied_row: MicrosoftRowText | None = None,
    not_found_row: MicrosoftRowText | None = None,
    invalid_row: MicrosoftRowText | None = None,
    request: str = "the request",
) -> NoReturn:
    """``denied`` names what a grant would open, ``missing`` what Graph did
    not find. Graph answers a URL on another tenant's host with a 400, which
    is a setting to fix, not a transient failure."""
    if error.status == 400:
        raise ConnectorValidationError(
            f"{missing} Graph said: {error.code}.",
            summary=invalid_row.summary if invalid_row else None,
            description=invalid_row.description if invalid_row else None,
        ) from error
    raise_for_graph_error(
        error,
        f"{denied}.",
        remediation=_READ_REMEDIATION,
        permanent_refusal_message=f"{missing} ({error.status} {error.code}).",
        denied_row=denied_row,
        not_found_row=not_found_row,
        request=request,
    )


def _raise_for_rest_error(
    error: MicrosoftGraphError,
    denied: str,
    missing: str,
    *,
    denied_row: MicrosoftRowText | None = None,
    not_found_row: MicrosoftRowText | None = None,
    request: str = "the request",
) -> NoReturn:
    """SharePoint REST refusals: the permission reads need a grant Graph
    reads do not. A 401 is a token SharePoint does not take for its host."""
    if error.status == 401:
        raise CredentialInvalidError(
            f"SharePoint rejected the app's token for its host ({error.code}).",
            summary=_REST_TOKEN_ROW.summary,
            description=_REST_TOKEN_ROW.description,
        ) from error
    raise_for_graph_error(
        error,
        f"{denied}.",
        remediation=_REST_REMEDIATION,
        permanent_refusal_message=f"{missing} ({error.status} {error.code}).",
        denied_row=denied_row,
        not_found_row=not_found_row,
        request=request,
    )


def _raise_for_site_error(error: MicrosoftGraphError, site_url: str) -> NoReturn:
    _raise_for_read_error(
        error,
        f"The app cannot read the site {site_url}",
        f"Graph has no site at {site_url}. Check the URL.",
        denied_row=_site_denied_row(site_url),
        not_found_row=_site_not_found_row(site_url),
        invalid_row=_site_invalid_row(site_url),
        request="the site read",
    )


def _raise_unexpected_site(error: RuntimeError, site_url: str) -> NoReturn:
    raise UnexpectedValidationError(
        str(error),
        summary="Unexpected site data from Microsoft",
        description=f"Microsoft answered for {site_url} without its ID.\n{_RETRY_LINE}",
    ) from error


def _is_site_refusal(error: MicrosoftGraphError) -> bool:
    """Graph refused this one site for good: no grant, gone, locked, or a URL
    it does not take."""
    return error.is_permanent_refusal or error.status == 400


# --- Probe scope ---


def _found_sites(
    gateway: SharepointSourceOperations, sites: list[SiteDescriptor]
) -> list[SiteDescriptor]:
    """The sites Graph finds. A site it refuses is left out: "Find selected
    sites" reports it."""
    found: list[SiteDescriptor] = []
    for site in sites:
        try:
            gateway.get_site_id(site_url=site.url)
        except MicrosoftGraphError as error:
            if not _is_site_refusal(error):
                _raise_for_site_error(error, site.url)
            continue
        except RuntimeError:
            continue
        found.append(site)
    return found


def _probe_sites(
    context: CapabilityCheckContext,
    *,
    found_only: bool = True,
    listed_limit: int = _PROBE_SITES,
) -> list[SiteDescriptor]:
    """The sites a probe reads: the first configured sites (those Graph finds,
    with ``found_only``), or without any the first ``listed_limit`` sites Graph
    lists.
    Configured sites the exclusions remove leave the scope empty, as they do
    for indexing."""
    config: SharepointConnectorConfig = _config(context)
    gateway: SharepointSourceOperations = _gateway(context)
    if _configured_sites(config):
        sites: list[SiteDescriptor] = _descriptors(config)[:_PROBE_SITES]
        return _found_sites(gateway, sites) if found_only else sites
    try:
        site_urls: list[str] = gateway.list_site_urls(max_pages=1).site_urls
    except MicrosoftGraphError as error:
        raise_for_graph_error(
            error,
            "The app cannot list the tenant's sites.",
            remediation=_READ_REMEDIATION,
            denied_row=_LIST_SITES_DENIED_ROW,
            request="the site listing",
        )
    patterns: list[str] = _excluded_patterns(config)
    return [
        SiteDescriptor(url=site_url, drive_name=None, folder_path=None)
        for site_url in site_urls
        if ONEDRIVE_HOST_MARKER not in site_url
        and not is_site_excluded(site_url, patterns)
    ][:listed_limit]


class _LibraryNotFound(ConnectorValidationError):
    """The site has no library of the name its URL gives."""


class _LibraryAmbiguous(ConnectorValidationError):
    """More than one library of the site matches the name its URL gives."""


def _raise_unexpected_library(error: DriveMetadataError) -> NoReturn:
    raise UnexpectedValidationError(
        str(error),
        summary=_UNEXPECTED_LIBRARY_ROW.summary,
        description=_UNEXPECTED_LIBRARY_ROW.description,
    ) from error


def _site_drives(
    context: CapabilityCheckContext, site: SiteDescriptor
) -> list[SiteDrive]:
    """The site's libraries, narrowed to the configured one when the site URL
    names a library."""
    try:
        drives: list[SharepointDrive] = _gateway(context).list_drives(site_url=site.url)
    except MicrosoftGraphError as error:
        _raise_for_read_error(
            error,
            f"The app cannot list the libraries of {site.url}",
            f"Graph has no site at {site.url}. Check the URL.",
            denied_row=_site_denied_row(site.url),
            not_found_row=_site_not_found_row(site.url),
            invalid_row=_site_invalid_row(site.url),
            request="the library listing",
        )
    try:
        if site.drive_name is None:
            return [site_drive_from_graph(drive) for drive in drives]
        selected: SiteDrive | None = select_site_drive(site, site.drive_name, drives)
    except DriveMetadataError as error:
        _raise_unexpected_library(error)
    except ValueError as error:
        ambiguous: MicrosoftRowText = _library_ambiguous_row(site.url)
        raise _LibraryAmbiguous(
            str(error), summary=ambiguous.summary, description=ambiguous.description
        ) from error
    if selected is None:
        kind: str = (
            "OneDrive" if PERSONAL_SITE_URL_MARKER in site.url.lower() else "library"
        )
        missing: MicrosoftRowText = _library_not_found_row(site.drive_name)
        raise _LibraryNotFound(
            f"No {kind} at `{site.drive_name}` in {site.url}. Use the library's "
            "URL segment (SharePoint strips characters like `&` from it).",
            summary=missing.summary,
            description=missing.description,
        )
    return [selected]


def _found_site_drives(
    context: CapabilityCheckContext, site: SiteDescriptor
) -> list[SiteDrive]:
    """The site's libraries in scope, empty when the library its URL names is
    missing or ambiguous: "Find selected libraries" reports that."""
    try:
        return _site_drives(context, site)
    except (_LibraryNotFound, _LibraryAmbiguous):
        return []


def _excluded_paths(config: SharepointConnectorConfig) -> list[str]:
    return [path.strip() for path in config.excluded_paths or [] if path.strip()]


def _is_indexable_file(
    item: DriveDeltaItem, folder_path: str | None, excluded_paths: list[str]
) -> bool:
    """The rows indexing turns into documents: a supported file inside the
    configured folder and outside the excluded paths. A OneNote notebook has
    no file facet and no content to read."""
    if item.file is None or item.is_tombstone:
        return False
    if get_file_ext(item.name or "") not in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS:
        return False
    data: DriveItemData = DriveItemData.from_graph_json(item.to_graph_json())
    # The same path indexing matches the exclusions against.
    relative_path: str = build_item_relative_path(data.parent_reference_path, data.name)
    if folder_path is not None:
        scope: str = folder_path.strip("/").casefold() + "/"
        if not relative_path.casefold().startswith(scope):
            return False
    return not is_path_excluded(relative_path, excluded_paths)


def _counted_sites(count: int) -> str:
    return "1 site" if count == 1 else f"{count} sites"


def _first_indexable_file(
    gateway: SharepointSourceOperations,
    graph_api_base: str,
    site: SiteDescriptor,
    drive: SiteDrive,
    excluded_paths: list[str],
) -> DriveItemData | None:
    """One delta page, the bounded listing. A library whose first page holds
    nothing indexing would read proves the listing and skips the file read."""
    try:
        result: DriveDeltaFetchResult = gateway.get_delta_page(
            drive_id=drive.drive_id,
            page_url=build_delta_start_url(
                graph_api_base, drive.drive_id, page_size=_PROBE_DELTA_PAGE_SIZE
            ),
            allow_full_resync=True,
        )
    except MicrosoftGraphError as error:
        _raise_for_read_error(
            error,
            f"The app cannot list the files of {drive.display_name} in {site.url}",
            f"Graph has no library {drive.display_name} in {site.url}.",
            denied_row=_row(
                _line("No read access to ", drive.display_name),
                f"The app can see the library but not list its files.\n{_READ_GRANT}",
            ),
            not_found_row=_library_unreadable_row(drive.display_name),
            invalid_row=_library_unreadable_row(drive.display_name),
            request="the file listing",
        )
    delta_item: DriveDeltaItem | None = next(
        (
            item
            for item in result.page.items
            if _is_indexable_file(item, site.folder_path, excluded_paths)
        ),
        None,
    )
    if delta_item is None:
        return None
    return DriveItemData.from_graph_json(delta_item.to_graph_json())


def _list_site_pages(
    gateway: SharepointSourceOperations, site_id: str
) -> SitePagesPage:
    """The expanded listing, else the plain one, the way indexing falls back
    when one corrupt canvas poisons the expanded listing."""
    try:
        return gateway.list_site_pages(site_id=site_id, expand_canvas=True)
    except MicrosoftGraphError as error:
        if not is_graph_invalid_request(error):
            raise
    return gateway.list_site_pages(site_id=site_id, expand_canvas=False)


def _site_id(gateway: SharepointSourceOperations, site: SiteDescriptor) -> str:
    try:
        return gateway.get_site_id(site_url=site.url)
    except MicrosoftGraphError as error:
        _raise_for_site_error(error, site.url)
    except RuntimeError as error:
        _raise_unexpected_site(error, site.url)


def _site_pages(
    gateway: SharepointSourceOperations, site: SiteDescriptor, site_id: str
) -> SitePagesPage | None:
    """The site's pages. None for a classic site, which has no pages listing
    and which indexing skips."""
    try:
        return _list_site_pages(gateway, site_id)
    except MicrosoftGraphError as error:
        if error.status == 404:
            return None
        name: str = _site_name(site.url)
        unreadable: MicrosoftRowText = _row(
            _line("Site pages not readable: ", name),
            f"Microsoft refused the page listing of {site.url}.\n{_LOCKED_LINE}",
        )
        _raise_for_read_error(
            error,
            f"The app cannot list the pages of {site.url}",
            f"Graph lists no pages for {site.url}.",
            denied_row=_row(
                _line("No permission to read pages of ", name),
                f"The app cannot list the pages of {site.url}.\n{_READ_GRANT}",
            ),
            not_found_row=unreadable,
            invalid_row=unreadable,
            request="the page listing",
        )


def _perm_probe_sites(context: CapabilityCheckContext) -> list[SiteDescriptor]:
    """The probe sites, which a permission read needs at least one of. The
    permission checks do not run after "Find selected sites", so a missing
    site fails their own SharePoint read."""
    sites: list[SiteDescriptor] = _probe_sites(context, found_only=False)
    if not sites:
        _raise_row(
            NothingToCheckError,
            "No site was found to probe, so no permission was read.",
            _NO_SITES_ROW,
        )
    return sites


def _site_assignments(
    gateway: SharepointSourceOperations, site: SiteDescriptor
) -> list[SharepointRoleAssignment]:
    """One page of the site's role assignments, the read every sync starts a
    site with."""
    try:
        return gateway.list_role_assignments(
            site_url=site.url,
            securable=_SITE_SECURABLE,
            max_rows=_PROBE_ROLE_ASSIGNMENTS,
        )
    except MicrosoftGraphError as error:
        _raise_for_rest_error(
            error,
            f"The app cannot read the permissions of {site.url}",
            f"SharePoint has no site at {site.url}. Check the URL.",
            denied_row=_site_permissions_denied_row(site.url),
            not_found_row=_site_not_found_row(site.url),
            request="the site permission read",
        )


def _first_group(
    assignments: list[SharepointRoleAssignment],
    principal_type: SharepointPrincipalType,
) -> SharepointPrincipal | None:
    """The first group of the type the sync would expand: one granting more
    than Limited Access, whose login does not mean everyone."""
    return next(
        (
            member
            for member in granting_members(assignments)
            if member.principal_type == principal_type
            and not is_public_login_name(member.login_name)
        ),
        None,
    )


def _site_group_users(
    gateway: SharepointSourceOperations,
    site: SiteDescriptor,
    site_group: SharepointPrincipal,
) -> list[SharepointPrincipal]:
    try:
        return gateway.list_site_group_users(
            site_url=site.url,
            group_name=site_group.login_name,
            max_rows=_PROBE_GROUP_MEMBERS,
        )
    except MicrosoftGraphError as error:
        _raise_for_rest_error(
            error,
            f"The app cannot read the members of `{site_group.title}` on {site.url}",
            f"SharePoint has no group `{site_group.title}` on {site.url}.",
            denied_row=_row(
                _line("No access to members of ", site_group.title),
                f"The app cannot read who is in the site group {site_group.title}."
                f"\n{_REST_GRANT}",
            ),
            not_found_row=_row(
                _line("Site group not found: ", site_group.title),
                "SharePoint listed this group and then did not find it.\nRe-run "
                "the checks.",
            ),
            request="the site group read",
        )


def _entra_group_principal(
    gateway: SharepointSourceOperations,
    site: SiteDescriptor,
    assignments: list[SharepointRoleAssignment],
) -> SharepointPrincipal | None:
    """The first Entra group the site names, directly or inside one of its
    first site groups, which the sync expands to reach nested Entra groups."""
    principal: SharepointPrincipal | None = _first_group(
        assignments, SharepointPrincipalType.ENTRA_GROUP
    )
    if principal is not None:
        return principal
    site_groups: list[SharepointPrincipal] = [
        member
        for member in granting_members(assignments)
        if member.principal_type == SharepointPrincipalType.SHAREPOINT_GROUP
    ][:_PROBE_SITE_GROUPS]
    for site_group in site_groups:
        principal = next(
            (
                member
                for member in _site_group_users(gateway, site, site_group)
                if member.principal_type == SharepointPrincipalType.ENTRA_GROUP
                and not is_public_login_name(member.login_name)
            ),
            None,
        )
        if principal is not None:
            return principal
    return None


class _EntraGroupRef(BaseModel):
    id: str
    name: str


def _entra_group(
    gateway: SharepointSourceOperations,
    site: SiteDescriptor,
    assignments: list[SharepointRoleAssignment],
) -> _EntraGroupRef | None:
    """The first Entra group the site names, with its Graph id resolved the
    way the sync resolves it. None when it names none."""
    principal: SharepointPrincipal | None = _entra_group_principal(
        gateway, site, assignments
    )
    if principal is None:
        return None
    group_id: str | None = resolve_group_id(gateway, principal.login_name)
    if group_id is None:
        # The sync logs a refused lookup and moves on. Read it once more so the
        # refusal names the grant.
        try:
            group_id = gateway.find_entra_group_id(display_name=principal.login_name)
        except MicrosoftGraphError as error:
            raise_for_graph_error(
                error,
                f"The app cannot look up the Entra group `{principal.title}`.",
                remediation=_GROUPS_REMEDIATION,
                denied_row=ENTRA_GROUPS_DENIED_ROW,
                request="the group lookup",
            )
    if group_id is None:
        # The sync skips a group Entra no longer knows by that name.
        logger.warning(
            "Graph has no Entra group for `%s` (%s), which the site names.",
            principal.title,
            principal.login_name,
        )
        return None
    return _EntraGroupRef(id=group_id, name=principal.title or group_id)


class _SharepointCheck(CapabilityCheck[SharepointConnectorConfig]):
    config_class = SharepointConnectorConfig

    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        capability: CredentialCapability = CredentialCapability.INDEXING,
        requires_connector_config: bool = True,
        validates_binding: bool = False,
        fails_when_unreachable: bool = False,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            requires_connector_instance=False,
            requires_connector_config=requires_connector_config,
            remediation=remediation,
            docs_link=_DOCS_LINK,
            validates_binding=validates_binding,
            fails_when_unreachable=fails_when_unreachable,
            depends_on=_DEPENDS_ON.get(check_id, ()),
        )


class _TokenCheck(_SharepointCheck):
    """Signs in against the authority the settings select, so the check waits
    for them: a national-cloud app fails against the commercial authority."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_SIGN_IN_CHECK_ID,
            display_name="Sign in to Microsoft",
            validates_binding=True,
            fails_when_unreachable=True,
            remediation=(
                "Check the client id, directory id and client secret or "
                "certificate, and that the Graph API and authority hosts match "
                "the app's cloud."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        signed_in: MicrosoftSignIn = sign_in(
            _gateway(context).check_token, _ACCOUNT_LABELS
        )
        return CheckOutput(
            summary=signed_in.summary,
            description=signed_in.description,
            advisories=[CheckAdvisory(message=caveat) for caveat in signed_in.caveats],
        )


_CONTENT_TYPE_NAMES = ("documents", "site pages")


class _ContentTypesCheck(_SharepointCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="sharepoint_content_types",
            display_name="Check selected content",
            remediation="Turn on site documents, site pages, or both.",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: SharepointConnectorConfig = _config(context)
        try:
            validate_content_types(
                config.include_site_documents, config.include_site_pages
            )
        except ConnectorValidationError as error:
            raise ConnectorValidationError(
                error.message,
                summary="No content type selected",
                description=(
                    "Neither Index Documents nor Index ASPX Sites is selected.\n"
                    "Select at least one: Index Documents or Index ASPX Sites."
                ),
            ) from error
        selected: list[str] = [
            name
            for name, included in zip(
                _CONTENT_TYPE_NAMES,
                (config.include_site_documents, config.include_site_pages),
                strict=True,
            )
            if included
        ]
        return CheckOutput(summary=f"Indexing {', '.join(selected)}")


class _SiteProblem(BaseModel):
    site_url: str
    row: MicrosoftRowText
    message: str
    denied: bool


def _site_problem(error: MicrosoftGraphError, site_url: str) -> _SiteProblem:
    if error.status == 403:
        row: MicrosoftRowText = _site_denied_row(site_url)
    elif error.status == 400:
        row = _site_invalid_row(site_url)
    else:
        row = _site_not_found_row(site_url)
    return _SiteProblem(
        site_url=site_url,
        row=row,
        message=(
            f"{site_url}: Graph refused the site ({error.status} {error.code})."
            + (f" {_READ_REMEDIATION}" if error.status == 403 else "")
        ),
        denied=error.status == 403,
    )


def _validate_site_urls(
    site_urls: list[str], environment: MicrosoftGraphEnvironment
) -> None:
    """Each URL is a full site URL, safe to request, on the first URL's
    tenant host: the rules indexing applies."""
    tenant_domain: str | None = tenant_domain_from_site_urls(site_urls)
    for site_url in site_urls:
        try:
            connector_utils.validate_site_url(
                site_url, environment.sharepoint_domain_suffix, tenant_domain
            )
        except SiteUrlFormatError as error:
            raise ConnectorValidationError(
                error.message,
                summary=_line("Not a site URL: ", site_url or "(blank)"),
                description=(
                    "A site URL must start with https:// and contain /sites/, "
                    "/teams/ or /personal/ followed by the site name."
                ),
            ) from error
        except SiteUrlBlockedError as error:
            raise ConnectorValidationError(
                error.message,
                summary=_line("Site URL not allowed: ", _site_name(site_url)),
                description=(
                    "The URL points at an address the server must not call.\nUse "
                    "the site's public SharePoint URL in Sites."
                ),
            ) from error
        except SiteUrlHostError as error:
            raise ConnectorValidationError(
                error.message,
                summary=_line("Site is on another host: ", _site_name(site_url)),
                description=(
                    "All sites must be on one tenant's SharePoint host.\nRemove "
                    f"{site_url} from Sites, or use its URL on this tenant's host."
                ),
            ) from error


def _first_problem_action(row: MicrosoftRowText) -> str:
    """The action line of a row's description."""
    return row.description.splitlines()[-1]


class _ConfiguredSitesCheck(_SharepointCheck):
    """The configured site URLs are well formed, on the tenant's host, and
    Graph finds each of the first few. Some missing is INCOMPLETE, and the
    checks after it run on the found ones; none found FAILS."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_CONFIGURED_SITES_CHECK_ID,
            display_name="Find selected sites",
            remediation=(
                "Use full site URLs on this tenant (https://tenant.sharepoint.com/"
                "sites/name or /teams/name, https://tenant-my.sharepoint.com/"
                "personal/name). " + _READ_REMEDIATION
            ),
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return bool(_configured_sites(form_state.config))

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: SharepointConnectorConfig = _config(context)
        site_urls: list[str] = _configured_sites(config)
        _validate_site_urls(
            site_urls,
            resolve_microsoft_environment(config.graph_api_host, config.authority_host),
        )
        parsed: list[SiteDescriptor] = extract_site_descriptors(site_urls)
        if len(parsed) != len(site_urls):
            # The connector drops a URL it cannot parse into a site, so the
            # admin would index nothing for it.
            parsed_urls: tuple[str, ...] = tuple(
                descriptor.url for descriptor in parsed
            )
            dropped: list[str] = [
                url for url in site_urls if not url.startswith(parsed_urls)
            ]
            raise ConnectorValidationError(
                f"These URLs name no site: {', '.join(dropped)}. A site URL ends "
                "in /sites/name, /teams/name or /personal/name.",
                summary=_line("URL names no site: ", dropped[0]),
                description=(
                    "The URL has no site name after /sites/, /teams/ or "
                    "/personal/.\nAdd the site name to the URL in Sites."
                ),
            )
        in_scope: list[SiteDescriptor] = _descriptors(config)
        if not in_scope:
            raise ConnectorValidationError(
                "Every configured site matches an excluded site pattern, so "
                "indexing reads nothing.",
                summary="Every selected site is excluded",
                description=(
                    "Each site in Sites matches a pattern in Excluded Sites.\n"
                    "Remove the match from Excluded Sites."
                ),
            )
        gateway: SharepointSourceOperations = _gateway(context)
        probed: list[SiteDescriptor] = in_scope[:_PROBE_SITES]
        problems: list[_SiteProblem] = [
            problem for site in probed if (problem := _probe_site(gateway, site))
        ]
        return _sites_output(in_scope, probed, problems)


def _probe_site(
    gateway: SharepointSourceOperations, site: SiteDescriptor
) -> _SiteProblem | None:
    """Why Graph refuses the site, None when it finds it."""
    try:
        gateway.get_site_id(site_url=site.url)
    except MicrosoftGraphError as error:
        if not _is_site_refusal(error):
            _raise_for_site_error(error, site.url)
        return _site_problem(error, site.url)
    except RuntimeError as error:
        _raise_unexpected_site(error, site.url)
    return None


def _sites_output(
    in_scope: list[SiteDescriptor],
    probed: list[SiteDescriptor],
    problems: list[_SiteProblem],
) -> CheckOutput:
    if not problems:
        if len(in_scope) > len(probed):
            return CheckOutput(
                summary=f"First {len(probed)} of {len(in_scope)} sites found",
                advisories=[
                    CheckAdvisory(
                        message=(
                            f"Only the first {len(probed)} sites were read. The "
                            "others were checked for format only."
                        )
                    )
                ],
            )
        return CheckOutput(
            summary=f"{_counted(len(probed), 'selected site', 'selected sites')} found"
        )
    message: str = "; ".join(problem.message for problem in problems)
    first: _SiteProblem = problems[0]
    names: str = ", ".join(_site_name(problem.site_url) for problem in problems)
    if len(problems) == len(probed):
        error_class: type[ConnectorValidationError] = (
            InsufficientPermissionsError
            if all(problem.denied for problem in problems)
            else ConnectorValidationError
        )
        if len(problems) == 1:
            _raise_row(error_class, message, first.row)
        _raise_row(
            error_class,
            message,
            _row(
                "No selected site found",
                "None of the selected sites is visible to this account.\n"
                f"Not found or refused: {names}. {_first_problem_action(first.row)}",
            ),
        )
    if len(problems) == 1:
        return CheckOutput(
            summary=first.row.summary, description=first.row.description, partial=True
        )
    return CheckOutput(
        summary=f"{len(problems)} of {len(probed)} sites not found",
        description=(
            f"Not found or refused: {names}.\n{_first_problem_action(first.row)}"
        ),
        partial=True,
    )


class _SitesVisibleCheck(_SharepointCheck):
    """Without configured sites the connector indexes every site it can list,
    which needs a tenant-wide read grant: `Sites.Selected` lists nothing."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_SITES_VISIBLE_CHECK_ID,
            display_name="List sites",
            remediation=(
                "Grant `Sites.Read.All` (application permission) and admin-consent "
                "it, or configure the site URLs to index."
            ),
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return not _configured_sites(form_state.config)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            listing: SiteUrlListing = _gateway(context).list_site_urls(max_pages=1)
        except MicrosoftGraphError as error:
            raise_for_graph_error(
                error,
                "The app cannot list the tenant's sites.",
                remediation=_READ_REMEDIATION,
                denied_row=_LIST_SITES_DENIED_ROW,
                request="the site listing",
            )
        site_urls: list[str] = listing.site_urls
        if not site_urls:
            raise InsufficientPermissionsError(
                "Graph lists no sites for this app. With `Sites.Selected` the "
                "listing is empty, so configure the site URLs to index.",
                summary="No sites visible to the app",
                description=f"The app sees no site in the tenant.\n{_READ_GRANT}",
            )
        patterns: list[str] = _excluded_patterns(_config(context))
        if all(is_site_excluded(site_url, patterns) for site_url in site_urls):
            if not listing.complete:
                raise InconclusiveValidationError(
                    "Every site on the first page of the site listing matches an "
                    "excluded site pattern. Later pages were not read.",
                    summary="No included site in the sample",
                    description=(
                        "The bounded sample found no included site.\nLater "
                        "sites in the listing can still be indexed."
                    ),
                )
            raise ConnectorValidationError(
                "Every listed site matches an excluded site pattern, so indexing "
                "reads nothing.",
                summary="Every listed site is excluded",
                description=(
                    "Each site the app lists matches a pattern in Excluded Sites.\n"
                    "Remove the match from Excluded Sites."
                ),
            )
        return CheckOutput(
            summary=f"{_counted(len(site_urls), 'site', 'sites')} visible"
        )


class _LibraryProblem(BaseModel):
    row: MicrosoftRowText
    message: str
    name: str


def _folder_problem(
    error: MicrosoftGraphError, site: SiteDescriptor, folder_url: str
) -> _LibraryProblem:
    folder: str = (site.folder_path or "").rstrip("/").rsplit("/", 1)[-1]
    missing: bool = error.status == 404
    return _LibraryProblem(
        row=_row(
            _line(
                "Folder not found: " if missing else "Folder path not valid: ", folder
            ),
            (
                "The library has no folder at this path."
                if missing
                else "Microsoft refused this folder path."
            )
            + "\nCopy the folder URL from the browser into Sites.",
        ),
        message=(
            f"No folder at {folder_url}. Check the path. ({error.status} {error.code})."
        ),
        name=site.folder_path or "",
    )


class _ConfiguredLibrariesCheck(_SharepointCheck):
    """A site URL that goes past the site names a library, and past that a
    folder, which must exist there. The documents probe reads one file and
    stops, so a missing second library would otherwise go unnoticed. Pages do
    not read libraries, so this is a documents rule. Some missing is
    INCOMPLETE, and the checks after it run on the found ones."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_CONFIGURED_LIBRARIES_CHECK_ID,
            display_name="Find selected libraries",
            remediation=(
                "Use the library's URL segment and the folder's path inside it "
                "as they appear in the site URL."
            ),
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return form_state.config.include_site_documents and any(
            site.drive_name for site in _descriptors(form_state.config)
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        named: list[SiteDescriptor] = [
            site for site in _descriptors(_config(context)) if site.drive_name
        ]
        scoped: list[SiteDescriptor] = _found_sites(
            _gateway(context), named[:_PROBE_SITES]
        )
        if not scoped:
            _raise_row(
                NothingToCheckError,
                "No site that names a library was found.",
                _row(
                    "No libraries to test",
                    "No site that names a library was found.\nSee Find selected sites.",
                ),
            )
        problems: list[_LibraryProblem] = [
            problem for site in scoped if (problem := self._probe(context, site))
        ]
        if not problems:
            if len(named) > len(scoped):
                return CheckOutput(
                    summary=f"First {len(scoped)} of {len(named)} libraries found",
                    advisories=[
                        CheckAdvisory(
                            message=(
                                f"Only the first {len(scoped)} site URLs that name "
                                "a library were checked."
                            )
                        )
                    ],
                )
            return CheckOutput(
                summary=(
                    _counted(len(scoped), "selected library", "selected libraries")
                    + " found"
                )
            )
        message: str = "; ".join(problem.message for problem in problems)
        first: _LibraryProblem = problems[0]
        names: str = ", ".join(problem.name for problem in problems)
        if len(problems) == len(scoped):
            _raise_row(
                ConnectorValidationError,
                message,
                first.row
                if len(problems) == 1
                else _row(
                    "No selected library found",
                    "None of the selected libraries is visible to this account.\n"
                    f"Not found: {names}.",
                ),
            )
        if len(problems) == 1:
            return CheckOutput(
                summary=first.row.summary,
                description=first.row.description,
                partial=True,
            )
        return CheckOutput(
            summary=f"{len(problems)} of {len(scoped)} libraries not found",
            description=(
                f"Not found: {names}.\nCopy each library or folder URL from the "
                "browser into Sites."
            ),
            partial=True,
        )

    def _probe(
        self, context: CapabilityCheckContext, site: SiteDescriptor
    ) -> _LibraryProblem | None:
        """Why the site's library or folder is missing, None when it is
        found. A refusal that a grant or a setting fixes raises."""
        try:
            drives: list[SiteDrive] = _site_drives(context, site)
        except _LibraryNotFound as error:
            return _LibraryProblem(
                row=_library_not_found_row(site.drive_name or ""),
                message=error.message,
                name=site.drive_name or "",
            )
        if not site.folder_path:
            return None
        folder_url: str = f"{site.url}/{site.drive_name}/{site.folder_path}"
        for drive in drives:
            try:
                _gateway(context).resolve_folder(
                    drive_id=drive.drive_id, folder_path=site.folder_path
                )
            except MicrosoftGraphError as error:
                if error.status in (400, 404):
                    return _folder_problem(error, site, folder_url)
                _raise_for_read_error(
                    error,
                    f"The app cannot read the folder {folder_url}",
                    f"No folder at {folder_url}. Check the path.",
                    denied_row=_row(
                        _line(
                            "No read access to ",
                            site.folder_path.rstrip("/").rsplit("/", 1)[-1],
                        ),
                        f"The app cannot read this folder.\n{_READ_GRANT}",
                    ),
                    request="the folder read",
                )
        return None


class _DocumentsReadCheck(_SharepointCheck):
    """The first non-empty probe library answers a delta page and lists its
    files, and one file reads by id, with its content when it is small.
    Without configured sites the probe reads listed sites in turn until one
    holds a file indexing would read."""

    def __init__(self) -> None:
        super().__init__(
            check_id="sharepoint_documents_read",
            display_name="Sample documents",
            remediation=_READ_REMEDIATION,
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return form_state.config.include_site_documents

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: SharepointSourceOperations = _gateway(context)
        config: SharepointConnectorConfig = _config(context)
        graph_api_base: str = _graph_api_base(config)
        probed: int = 0
        sites_read: int = 0
        excluded_paths: list[str] = _excluded_paths(config)
        for site in _probe_sites(context, listed_limit=_PROBE_SAMPLE_SITES):
            sites_read += 1
            for drive in _found_site_drives(context, site):
                if probed == _PROBE_SAMPLE_LIBRARIES:
                    return _no_sample_file(probed, sites_read)
                probed += 1
                item: DriveItemData | None = _first_indexable_file(
                    gateway, graph_api_base, site, drive, excluded_paths
                )
                if item is None:
                    continue
                self._read_one(gateway, drive, item)
                return CheckOutput(summary=_line("Read a file in ", drive.display_name))
        if not probed:
            _raise_row(
                NothingToCheckError,
                "No library was found on the probe sites, so no file was read.",
                _NO_LIBRARIES_ROW,
            )
        return _no_sample_file(probed, sites_read)

    def _read_one(
        self, gateway: SharepointSourceOperations, drive: SiteDrive, item: DriveItemData
    ) -> None:
        try:
            found: DriveItemData | None = gateway.get_drive_item(
                drive_id=drive.drive_id, item_id=item.id
            )
            if found is None:
                _raise_row(
                    InconclusiveValidationError,
                    f"Graph listed `{item.name}` and then did not answer it by id.",
                    _FILE_GONE_ROW,
                )
            if item.size is not None and item.size <= _MAX_PROBE_DOWNLOAD_BYTES:
                gateway.read_item_bytes(
                    drive_id=drive.drive_id,
                    item=item,
                    max_bytes=_MAX_PROBE_DOWNLOAD_BYTES,
                )
        except MicrosoftGraphError as error:
            if error.status == 404:
                raise InconclusiveValidationError(
                    f"`{item.name}` in {drive.display_name} went away before the "
                    "check read it.",
                    summary=_FILE_GONE_ROW.summary,
                    description=_FILE_GONE_ROW.description,
                ) from error
            raise_for_graph_error(
                error,
                f"The app cannot read `{item.name}` in {drive.display_name}.",
                remediation=_READ_REMEDIATION,
                denied_row=_row(
                    _line("No read access to files in ", drive.display_name),
                    f"Documents in {drive.display_name} would index without "
                    f"content.\n{_READ_GRANT}",
                ),
                request="the file read",
            )


def _libraries_probed(probed: int, limit: int = _PROBE_LIBRARIES) -> str:
    """The libraries a probe read, for a line: "The first 10 libraries", "The
    library"."""
    if probed == limit:
        return f"The first {probed} libraries"
    return "The library" if probed == 1 else f"The {probed} libraries"


def _no_sample_file(probed: int, sites_read: int) -> NoReturn:
    libraries: str = (
        f"{_libraries_probed(probed, _PROBE_SAMPLE_LIBRARIES)}, on "
        f"{_counted_sites(sites_read)},"
    )
    raise InconclusiveValidationError(
        f"{libraries} list no file indexing would read, so no file was read.",
        summary="No files found to test",
        description=(
            f"{libraries} hold no file indexing would read in their first rows."
        ),
    )


class _SitePagesReadCheck(_SharepointCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="sharepoint_site_pages_read",
            display_name="Sample site pages",
            remediation=_READ_REMEDIATION,
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return form_state.config.include_site_pages

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: SharepointSourceOperations = _gateway(context)
        for site in _probe_sites(context):
            site_id: str = _site_id(gateway, site)
            listing: SitePagesPage | None = _site_pages(gateway, site, site_id)
            page_id: str | None = next(
                (
                    page["id"]
                    for page in (listing.pages if listing else [])
                    if page.get("id")
                ),
                None,
            )
            if page_id is None:
                continue
            passed: CheckOutput = CheckOutput(
                summary=_line("Read a page on ", _site_name(site.url))
            )
            try:
                gateway.get_site_page(
                    site_id=site_id, page_id=page_id, expand_canvas=True
                )
            except MicrosoftGraphError as error:
                # Indexing keeps the page's metadata when its canvas is
                # corrupt, so that is not a failure of the grant.
                if is_graph_invalid_request(error):
                    return passed
                if error.status == 404:
                    raise InconclusiveValidationError(
                        f"Graph lists page {page_id} of {site.url} and then has no "
                        "page.",
                        summary="Sample page disappeared",
                        description=(
                            "The page was deleted between the listing and the "
                            "read.\nRe-run the checks."
                        ),
                    ) from error
                _raise_for_read_error(
                    error,
                    f"The app cannot read a page of {site.url}",
                    f"Graph lists page {page_id} of {site.url} and then has no page.",
                    denied_row=_row(
                        _line("No permission to read pages of ", _site_name(site.url)),
                        f"The app cannot read the pages of {site.url}.\n{_READ_GRANT}",
                    ),
                    request="the page read",
                )
            return passed
        _raise_row(
            NothingToCheckError,
            "The probe sites list no modern page, so no page was read.",
            _NO_PAGES_ROW,
        )


class _CertificateAuthCheck(_SharepointCheck):
    """SharePoint REST accepts an app-only token only from a certificate, so
    no grant makes a client-secret credential sync permissions."""

    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id=_CERTIFICATE_CHECK_ID,
            display_name="Sign in with certificate",
            remediation=_CERTIFICATE_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: SharepointSourceOperations = _gateway(context)
        try:
            method: MicrosoftAuthMethod = gateway.get_auth_method()
            not_after: datetime | None = gateway.get_certificate_not_after()
        except MicrosoftAuthError as error:
            raise_for_auth_error(error, _ACCOUNT_LABELS)
        if not method.supports_sharepoint_rest:
            raise ConnectorValidationError(
                "Permission sync needs the SharePoint REST API, which only accepts "
                "app-only tokens from certificate authentication. This credential "
                "uses a client secret, so SharePoint denies the request no matter "
                "which permissions are granted.",
                summary="Account uses a client secret",
                description=(
                    "SharePoint reads permissions only for certificate accounts.\n"
                    "Create a new account with Certificate Authentication and "
                    "switch the connector to it."
                ),
            )
        if not_after is None:
            return CheckOutput(summary="Signed in with a certificate")
        return CheckOutput(summary=f"Certificate valid until {format_date(not_after)}")


class _SitePermissionsCheck(_SharepointCheck):
    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id="sharepoint_site_permissions_read",
            display_name="Read site permissions",
            remediation=_REST_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: SharepointSourceOperations = _gateway(context)
        sites: list[SiteDescriptor] = _perm_probe_sites(context)
        for site in sites:
            _site_assignments(gateway, site)
        return CheckOutput(
            summary=f"Read permissions of {_counted(len(sites), 'site', 'sites')}"
        )


class _SiteGroupMembersCheck(_SharepointCheck):
    """The members of a SharePoint group a probe site names, the REST read
    that expands site groups. Sites naming none have nothing to expand."""

    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id="sharepoint_site_group_members_read",
            display_name="Read site group members",
            remediation=_REST_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: SharepointSourceOperations = _gateway(context)
        for site in _perm_probe_sites(context):
            group: SharepointPrincipal | None = _first_group(
                _site_assignments(gateway, site),
                SharepointPrincipalType.SHAREPOINT_GROUP,
            )
            if group is None:
                continue
            _site_group_users(gateway, site, group)
            return CheckOutput(summary=_line("Read members of ", group.title))
        _raise_row(
            NothingToCheckError,
            "The probe sites grant no SharePoint group, so no group was read.",
            _row(
                "No site groups to test",
                "The sites in scope grant no SharePoint group.",
            ),
        )


class _EntraNestedGroupsCheck(_SharepointCheck):
    """The groups inside an Entra group a probe site names: document sync
    resolves a document's groups through this read, never their users. A
    group Entra no longer has is skipped, as the sync skips it."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="sharepoint_entra_nested_groups_read",
            display_name="Read nested groups",
            remediation=_GROUPS_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: SharepointSourceOperations = _gateway(context)
        for site in _perm_probe_sites(context):
            group: _EntraGroupRef | None = _entra_group(
                gateway, site, _site_assignments(gateway, site)
            )
            if group is None:
                continue
            try:
                gateway.list_nested_entra_groups(
                    group_id=group.id, max_rows=_PROBE_NESTED_GROUPS
                )
            except MicrosoftGraphError as error:
                if error.status == 404:
                    continue
                raise_for_graph_error(
                    error,
                    f"The app cannot read the groups inside Entra group {group.id}.",
                    remediation=_GROUPS_REMEDIATION,
                    denied_row=_row(
                        "No permission to read nested groups",
                        "Readers granted through nested groups would be missed.\n"
                        f"{_GROUPS_GRANT}",
                    ),
                    request="the nested group read",
                )
            return CheckOutput(summary=_line("Read groups inside ", group.name))
        _raise_row(
            NothingToCheckError,
            "The probe sites grant no Entra group the check could resolve.",
            _row(
                "No Entra groups to test",
                "The sites in scope grant no Entra group the check could resolve.",
            ),
        )


def _read_member_page(
    gateway: SharepointSourceOperations, group_id: str, name: str
) -> bool:
    """False for a group Entra no longer has, which the sync skips."""
    try:
        gateway.list_entra_group_member_page(group_id=group_id)
    except MicrosoftGraphError as error:
        if error.status == 404:
            return False
        if error.status == _LOCKED_STATUS:
            raise UnexpectedValidationError(
                f"The app cannot read the members of Entra group {group_id}.",
                summary=_line("Group is locked: ", name),
                description=f"Microsoft refused the member read.\n{_RETRY_LINE}",
            ) from error
        raise_for_graph_error(
            error,
            f"The app cannot read the members of Entra group {group_id}.",
            remediation=_GROUPS_REMEDIATION,
            denied_row=_row(
                "No permission to read group members",
                f"The app can list groups but not read their members.\n{_GROUPS_GRANT}",
            ),
            request="the group member read",
        )
    return True


def _first_listed_group(gateway: SharepointSourceOperations) -> EntraGroup | None:
    """The first named group of the tenant-wide listing, under the group
    listing grant."""
    try:
        page: EntraPage[EntraGroup] = gateway.list_entra_groups(page_size=1)
    except MicrosoftGraphError as error:
        raise_for_graph_error(
            error,
            "The app cannot list the tenant's Entra groups.",
            remediation=_GROUPS_REMEDIATION,
            denied_row=ENTRA_GROUPS_DENIED_ROW,
            request="the group listing",
        )
    return next(
        (group for group in page.items if group.id and group.display_name), None
    )


class _EntraGroupMembersCheck(_SharepointCheck):
    """One page of the members of an Entra group a probe site names, under
    the grant group sync expands groups with. One page proves the grant
    without walking a large group. When no probe site names an Entra group,
    one listed group stands in, since a later site may name one."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="sharepoint_entra_group_members_read",
            display_name="Read group members",
            remediation=_GROUPS_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: SharepointSourceOperations = _gateway(context)
        for site in _perm_probe_sites(context):
            group: _EntraGroupRef | None = _entra_group(
                gateway, site, _site_assignments(gateway, site)
            )
            if group is not None and _read_member_page(gateway, group.id, group.name):
                return CheckOutput(summary=_line("Read members of ", group.name))
        fallback: EntraGroup | None = _first_listed_group(gateway)
        if fallback is not None:
            name: str = fallback.display_name or fallback.id
            if _read_member_page(gateway, fallback.id, name):
                return CheckOutput(summary=_line("Read members of ", name))
        _raise_row(
            NothingToCheckError,
            "No Entra group was found to read.",
            _row("No Entra groups to test", "No Entra group was found to read."),
        )


class _EntraGroupEnumerationCheck(_SharepointCheck):
    """The tenant-wide group listing and one member page, the reads behind
    exhaustive Entra enumeration."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id=_GROUP_ENUMERATION_CHECK_ID,
            display_name="List groups",
            remediation=_GROUPS_REMEDIATION,
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return form_state.config.exhaustive_ad_enumeration

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: SharepointSourceOperations = _gateway(context)
        group: EntraGroup | None = _first_listed_group(gateway)
        if group is None:
            _raise_row(
                NothingToCheckError,
                "The tenant lists no named Entra group.",
                _row("No Entra groups to test", "The tenant listed no group."),
            )
        name: str = group.display_name or group.id
        if not _read_member_page(gateway, group.id, name):
            raise InconclusiveValidationError(
                f"Entra group {group.id} went away before its members were read.",
                summary="Sample group disappeared",
                description=(
                    "The group was deleted between the listing and the member "
                    "read.\nRe-run the checks."
                ),
            )
        return CheckOutput(summary=_line("Listed groups, read ", name))


class _FileGone(Exception):
    """The sample file went away between the listing and a read."""


class _DocumentPermissionsCheck(_SharepointCheck):
    """Library, folder and file permissions on the first probe library with a
    list id: the reads behind a library's node, a folder's node and a
    document. A library without a list id is skipped, as the sync skips it."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="sharepoint_document_permissions_read",
            display_name="Read file permissions",
            remediation=_REST_REMEDIATION,
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return form_state.config.include_site_documents

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: SharepointSourceOperations = _gateway(context)
        config: SharepointConnectorConfig = _config(context)
        graph_api_base: str = _graph_api_base(config)
        excluded_paths: list[str] = _excluded_paths(config)
        probed: int = 0
        for site in _perm_probe_sites(context):
            for drive in _found_site_drives(context, site):
                if drive.list_id is None:
                    continue
                if probed == _PROBE_LIBRARIES:
                    return _no_permission_sample(probed)
                probed += 1
                self._read_library(gateway, site, drive, drive.list_id)
                item: DriveItemData | None = _first_indexable_file(
                    gateway, graph_api_base, site, drive, excluded_paths
                )
                if item is None:
                    continue
                try:
                    self._read_folder(gateway, site, drive, item)
                    self._read_item(gateway, config, site, drive, drive.list_id, item)
                except _FileGone:
                    logger.info(
                        "`%s` went away before its permissions were read.", item.name
                    )
                    return CheckOutput(
                        summary="Sample file disappeared",
                        advisories=[
                            CheckAdvisory(
                                message=(
                                    "The file was deleted during the check, so its "
                                    "permissions were not read. Library "
                                    "permissions were."
                                )
                            )
                        ],
                    )
                return CheckOutput(
                    summary=_line("Read permissions of a file in ", drive.display_name)
                )
        if not probed:
            _raise_row(
                NothingToCheckError,
                "No library with a list id was found on the probe sites, so no "
                "document permission was read.",
                _row(
                    "No libraries in scope",
                    "No library in scope can carry permissions.",
                ),
            )
        return _no_permission_sample(probed)

    def _read_library(
        self,
        gateway: SharepointSourceOperations,
        site: SiteDescriptor,
        drive: SiteDrive,
        list_id: str,
    ) -> None:
        try:
            gateway.list_role_assignments(
                site_url=site.url,
                securable=SharepointSecurable(
                    kind=SharepointSecurableKind.LIBRARY, list_id=list_id
                ),
                max_rows=_PROBE_ROLE_ASSIGNMENTS,
            )
        except MicrosoftGraphError as error:
            _raise_for_rest_error(
                error,
                f"The app cannot read the permissions of {drive.display_name} "
                f"in {site.url}",
                f"SharePoint has no library {drive.display_name} in {site.url}.",
                denied_row=_row(
                    _line("No access to permissions of ", drive.display_name),
                    "The app cannot read who has access to this library.\n"
                    f"{_REST_GRANT}",
                ),
                not_found_row=_library_not_found_row(drive.display_name),
                request="the library permission read",
            )

    def _read_folder(
        self,
        gateway: SharepointSourceOperations,
        site: SiteDescriptor,
        drive: SiteDrive,
        item: DriveItemData,
    ) -> None:
        """The file's folder, the node the sync reads before the file. A file
        at the library root has none. A folder SharePoint no longer finds is
        skipped, as the sync skips its node."""
        relative_path: str = build_item_relative_path(
            item.parent_reference_path, item.name
        )
        if "/" not in relative_path:
            return
        folder_path: str = relative_path.rsplit("/", 1)[0]
        server_relative_path: str = build_folder_server_relative_path(
            drive.web_url, folder_path
        )
        try:
            folder_unique_id: str = gateway.get_folder_unique_id(
                site_url=site.url, server_relative_path=server_relative_path
            )
            gateway.list_role_assignments(
                site_url=site.url,
                securable=SharepointSecurable(
                    kind=SharepointSecurableKind.FOLDER,
                    folder_unique_id=folder_unique_id,
                ),
                max_rows=_PROBE_ROLE_ASSIGNMENTS,
            )
        except RuntimeError as error:
            raise UnexpectedValidationError(
                str(error),
                summary="Unexpected folder data from Microsoft",
                description=(
                    f"SharePoint answered for a folder without its ID.\n{_RETRY_LINE}"
                ),
            ) from error
        except MicrosoftGraphError as error:
            if error.status == 404:
                return
            _raise_for_rest_error(
                error,
                f"The app cannot read the permissions of folder {server_relative_path}",
                f"SharePoint has no folder at {server_relative_path}.",
                denied_row=_row(
                    "No permission to read folder permissions",
                    f"The app cannot read who has access to a folder.\n{_REST_GRANT}",
                ),
                not_found_row=_row(
                    _line("Folder is locked: ", folder_path.rsplit("/", 1)[-1]),
                    f"SharePoint refused the folder read.\n{_LOCKED_LINE}",
                ),
                request="the folder permission read",
            )

    def _read_item(
        self,
        gateway: SharepointSourceOperations,
        config: SharepointConnectorConfig,
        site: SiteDescriptor,
        drive: SiteDrive,
        list_id: str,
        item: DriveItemData,
    ) -> None:
        """Raises ``_FileGone`` when the file went away between the listing
        and a read: a per-item failure for the sync, not a grant problem."""
        if config.treat_sharing_link_as_public:
            try:
                gateway.list_sharing_link_scopes(
                    item=item, max_rows=_PROBE_SHARING_LINKS
                )
            except MicrosoftGraphError as error:
                if error.status == 404:
                    raise _FileGone from error
                raise_for_graph_error(
                    error,
                    f"The app cannot read the sharing links of `{item.name}`.",
                    remediation=_READ_REMEDIATION,
                    denied_row=_row(
                        "No permission to read sharing links",
                        "Links that make files public would be missed.\nGrant "
                        "`Sites.Read.All` and admin-consent it.",
                    ),
                    not_found_row=_row(
                        _line("File is locked: ", item.name),
                        f"Microsoft refused the sharing-link read.\n{_LOCKED_LINE}",
                    ),
                    request="the sharing-link read",
                )
        try:
            item_id: int | None = gateway.get_list_item_id(item=item)
        except MicrosoftGraphError as error:
            if error.status == 404:
                raise _FileGone from error
            raise_for_graph_error(
                error,
                f"The app cannot read the list item id of `{item.name}`.",
                remediation=_READ_REMEDIATION,
                denied_row=_row(
                    "No permission to read file details",
                    f"The app cannot read a file's list item.\n{_READ_GRANT}",
                ),
                request="the file detail read",
            )
        if item_id is None:
            raise UnexpectedValidationError(
                f"Graph lists `{item.name}` without its list item id, so its "
                "permissions cannot be read.",
                summary="Unexpected file data from Microsoft",
                description=(
                    "Microsoft listed a file without the ID its permissions are "
                    f"read by.\n{_RETRY_LINE}"
                ),
            )
        try:
            gateway.list_role_assignments(
                site_url=site.url,
                securable=SharepointSecurable(
                    kind=SharepointSecurableKind.LIST_ITEM,
                    list_id=list_id,
                    item_id=item_id,
                ),
                max_rows=_PROBE_ROLE_ASSIGNMENTS,
            )
        except MicrosoftGraphError as error:
            if error.status == 404:
                raise _FileGone from error
            _raise_for_rest_error(
                error,
                f"The app cannot read the permissions of `{item.name}` in "
                f"{drive.display_name}",
                f"SharePoint has no item `{item.name}` in {drive.display_name}.",
                denied_row=_row(
                    "No permission to read file permissions",
                    f"The app cannot read who has access to a file.\n{_REST_GRANT}",
                ),
                request="the file permission read",
            )


def _no_permission_sample(probed: int) -> NoReturn:
    raise InconclusiveValidationError(
        f"{_libraries_probed(probed)} in scope list no file the sync would read, "
        "so only library permissions were read.",
        summary="No files found to test",
        description="Library permissions were read, but no file was found.",
    )


class _PagePermissionsCheck(_SharepointCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="sharepoint_page_permissions_read",
            display_name="Read page permissions",
            remediation=_REST_REMEDIATION,
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return form_state.config.include_site_pages

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: SharepointSourceOperations = _gateway(context)
        vanished: bool = False
        for site in _perm_probe_sites(context):
            site_id: str = _site_id(gateway, site)
            listing: SitePagesPage | None = _site_pages(gateway, site, site_id)
            page_url: str | None = next(
                (
                    page["webUrl"]
                    for page in (listing.pages if listing else [])
                    if page.get("webUrl")
                ),
                None,
            )
            if page_url is None:
                continue
            try:
                gateway.list_role_assignments(
                    site_url=site.url,
                    securable=SharepointSecurable(
                        kind=SharepointSecurableKind.PAGE, page_url=page_url
                    ),
                    max_rows=_PROBE_ROLE_ASSIGNMENTS,
                )
            except MicrosoftGraphError as error:
                # A page that went away between the listing and the read is a
                # per-item failure for the sync, not a grant problem.
                if error.status == 404:
                    vanished = True
                    continue
                _raise_for_rest_error(
                    error,
                    f"The app cannot read the permissions of page {page_url}",
                    f"SharePoint has no page at {page_url}.",
                    denied_row=_row(
                        "No permission to read page permissions",
                        "The app cannot read who has access to a site page.\n"
                        f"{_REST_GRANT}",
                    ),
                    not_found_row=_row(
                        _line("Page is locked: ", _site_name(page_url)),
                        f"SharePoint refused the page permission read.\n{_LOCKED_LINE}",
                    ),
                    request="the page permission read",
                )
            return CheckOutput(
                summary=_line("Read permissions of a page on ", _site_name(site.url))
            )
        if vanished:
            raise InconclusiveValidationError(
                "The sampled page went away before its permissions were read.",
                summary="Sample page disappeared",
                description=(
                    "The page was deleted between the listing and the permission "
                    "read.\nRe-run the checks."
                ),
            )
        _raise_row(
            NothingToCheckError,
            "The probe sites list no modern page, so no page permission was read.",
            _NO_PAGES_ROW,
        )


def build_sharepoint_indexing_checks() -> list[CapabilityCheck]:
    return [
        _TokenCheck(),
        _ContentTypesCheck(),
        _SitesVisibleCheck(),
        _ConfiguredSitesCheck(),
        _ConfiguredLibrariesCheck(),
        _DocumentsReadCheck(),
        _SitePagesReadCheck(),
    ]


def build_sharepoint_doc_permission_sync_checks() -> list[CapabilityCheck]:
    capability: CredentialCapability = CredentialCapability.DOC_PERMISSION_SYNC
    return [
        _CertificateAuthCheck(capability),
        _SitePermissionsCheck(capability),
        _SiteGroupMembersCheck(capability),
        _DocumentPermissionsCheck(),
        _PagePermissionsCheck(),
        _EntraNestedGroupsCheck(),
    ]


def build_sharepoint_group_sync_checks() -> list[CapabilityCheck]:
    capability: CredentialCapability = CredentialCapability.EXTERNAL_GROUP_SYNC
    return [
        _CertificateAuthCheck(capability),
        _SitePermissionsCheck(capability),
        _SiteGroupMembersCheck(capability),
        _EntraGroupEnumerationCheck(),
        _EntraGroupMembersCheck(),
    ]
