"""Capability checks for the SharePoint connector.

The indexing checks register in ``registry.py``, the permission-sync checks in
the EE registry. Each check makes small probes (one page, one item, one group)
with the gateway operations the connector calls, on probe sites: the first few
configured sites, else the first few Graph lists.

The settings rules the connector's own validation applies (one content type
on, well-formed site URLs on the tenant's host) are checks too, since the
named checks replace that validation at creation.
"""

from typing import NoReturn

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
    form_config,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    UnexpectedValidationError,
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
from onyx.connectors.sharepoint.config import SharepointConnectorConfig
from onyx.connectors.sharepoint.connector import (
    ONEDRIVE_HOST_MARKER,
    PERSONAL_SITE_URL_MARKER,
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
    tenant_domain_from_site_urls,
    validate_content_types,
    validate_site_url,
)
from onyx.connectors.sharepoint.models import SharepointDrive, SitePagesPage
from onyx.connectors.sharepoint.source_operations import (
    GRAPH_API_VERSION,
    SharepointSourceOperations,
)
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.utils.logger import setup_logger

logger = setup_logger()

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/sharepoint"
_PROBE_SITES = 5
# Libraries whose first delta page holds no indexable file before the probe
# stops, so a tenant of empty libraries cannot spend the check's budget.
_PROBE_LIBRARIES = 10
# Site groups searched for an Entra group when the site names none directly,
# the way the sync expands site groups to find the Entra groups inside them.
_PROBE_SITE_GROUPS = 5
# One page each: a probe proves the read without walking a large permission
# list, site group or Entra group.
_PROBE_ROLE_ASSIGNMENTS = 100
_PROBE_GROUP_MEMBERS = 50
_PROBE_NESTED_GROUPS = 50
# A delta page lists folders before files, so one row is rarely a file.
_PROBE_DELTA_PAGE_SIZE = 25
# A download probe reads one real file. A large one would spend the check's
# time budget on bytes the check learns nothing from.
_MAX_PROBE_DOWNLOAD_BYTES = 5 * 1024 * 1024
_READ_REMEDIATION = (
    "Grant `Sites.Read.All` (application permission) and admin-consent it, or "
    "with `Sites.Selected` grant the app read access on each configured site."
)
_REST_REMEDIATION = (
    "Grant `Sites.FullControl.All` (application permission) and admin-consent "
    "it, or with `Sites.Selected` grant the app full control on each configured "
    "site."
)
_GROUPS_REMEDIATION = (
    "Grant `GroupMember.Read.All` (application permission) and admin-consent it."
)
_CERTIFICATE_REMEDIATION = (
    "Recreate the credential with Certificate Authentication, or turn permission "
    "sync off."
)
_SITE_SECURABLE = SharepointSecurable(kind=SharepointSecurableKind.SITE)


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


def _raise_for_read_error(
    error: MicrosoftGraphError, denied: str, missing: str
) -> NoReturn:
    """``denied`` names what a grant would open, ``missing`` what Graph did
    not find. Graph answers a URL on another tenant's host with a 400, which
    is a setting to fix, not a transient failure."""
    if error.status == 400:
        raise ConnectorValidationError(
            f"{missing} Graph said: {error.code}."
        ) from error
    raise_for_graph_error(
        error,
        f"{denied}.",
        remediation=_READ_REMEDIATION,
        permanent_refusal_message=f"{missing} ({error.status} {error.code}).",
    )


def _raise_for_rest_error(
    error: MicrosoftGraphError, denied: str, missing: str
) -> NoReturn:
    """SharePoint REST refusals: the permission reads need a grant Graph
    reads do not."""
    raise_for_graph_error(
        error,
        f"{denied}.",
        remediation=_REST_REMEDIATION,
        permanent_refusal_message=f"{missing} ({error.status} {error.code}).",
    )


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


def _probe_sites(context: CapabilityCheckContext) -> list[SiteDescriptor]:
    """The sites a probe reads: the first configured sites, or without any
    the first sites Graph lists. Configured sites the exclusions remove leave
    the scope empty, as they do for indexing."""
    config: SharepointConnectorConfig = _config(context)
    if _configured_sites(config):
        return _descriptors(config)[:_PROBE_SITES]
    try:
        site_urls: list[str] = _gateway(context).list_site_urls(max_pages=1)
    except MicrosoftGraphError as error:
        raise_for_graph_error(
            error,
            "The app cannot list the tenant's sites.",
            remediation=_READ_REMEDIATION,
        )
    patterns: list[str] = _excluded_patterns(config)
    return [
        SiteDescriptor(url=site_url, drive_name=None, folder_path=None)
        for site_url in site_urls
        if ONEDRIVE_HOST_MARKER not in site_url
        and not is_site_excluded(site_url, patterns)
    ][:_PROBE_SITES]


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
        )
    if site.drive_name is None:
        return [site_drive_from_graph(drive) for drive in drives]
    try:
        selected: SiteDrive | None = select_site_drive(site, site.drive_name, drives)
    except ValueError as error:
        raise ConnectorValidationError(str(error)) from error
    if selected is None:
        kind: str = (
            "OneDrive" if PERSONAL_SITE_URL_MARKER in site.url.lower() else "library"
        )
        raise ConnectorValidationError(
            f"No {kind} at `{site.drive_name}` in {site.url}. Use the library's "
            "URL segment (SharePoint strips characters like `&` from it)."
        )
    return [selected]


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


def _perm_probe_sites(context: CapabilityCheckContext) -> list[SiteDescriptor]:
    """The probe sites, which a permission read needs at least one of."""
    sites: list[SiteDescriptor] = _probe_sites(context)
    if not sites:
        raise UnexpectedValidationError(
            "No site was found to probe, so no permission was read."
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
        try:
            members: list[SharepointPrincipal] = gateway.list_site_group_users(
                site_url=site.url,
                group_name=site_group.login_name,
                max_rows=_PROBE_GROUP_MEMBERS,
            )
        except MicrosoftGraphError as error:
            _raise_for_rest_error(
                error,
                f"The app cannot read the members of `{site_group.title}` on {site.url}",
                f"SharePoint has no group `{site_group.title}` on {site.url}.",
            )
        principal = next(
            (
                member
                for member in members
                if member.principal_type == SharepointPrincipalType.ENTRA_GROUP
                and not is_public_login_name(member.login_name)
            ),
            None,
        )
        if principal is not None:
            return principal
    return None


def _entra_group_id(
    gateway: SharepointSourceOperations,
    site: SiteDescriptor,
    assignments: list[SharepointRoleAssignment],
) -> str | None:
    """The Graph id of the first Entra group the site names, resolved the way
    the sync resolves it. None when it names none."""
    principal: SharepointPrincipal | None = _entra_group_principal(
        gateway, site, assignments
    )
    if principal is None:
        return None
    group_id: str | None = resolve_group_id(gateway, principal.login_name)
    if group_id is not None:
        return group_id
    # The sync logs a refused lookup and moves on. Read it once more so the
    # refusal names the grant.
    try:
        group_id = gateway.find_entra_group_id(display_name=principal.login_name)
    except MicrosoftGraphError as error:
        raise_for_graph_error(
            error,
            f"The app cannot look up the Entra group `{principal.title}`.",
            remediation=_GROUPS_REMEDIATION,
        )
    if group_id is None:
        # The sync skips a group Entra no longer knows by that name.
        logger.warning(
            "Graph has no Entra group for `%s` (%s), which the site names.",
            principal.title,
            principal.login_name,
        )
    return group_id


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
        )


class _TokenCheck(_SharepointCheck):
    """Signs in against the authority the settings select, so the check waits
    for them: a national-cloud app fails against the commercial authority."""

    def __init__(self) -> None:
        super().__init__(
            check_id="sharepoint_token_auth",
            display_name="App registration can sign in",
            validates_binding=True,
            remediation=(
                "Check the client id, directory id and client secret or "
                "certificate, and that the Graph API and authority hosts match "
                "the app's cloud."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            _gateway(context).check_token()
        except MicrosoftAuthError as error:
            raise_for_auth_error(error)
        except MicrosoftGraphError as error:
            raise_for_graph_error(error, "Microsoft refused the token request.")


class _ContentTypesCheck(_SharepointCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="sharepoint_content_types",
            display_name="A content type is selected",
            remediation="Turn on site documents, site pages, or both.",
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config: SharepointConnectorConfig = _config(context)
        validate_content_types(config.include_site_documents, config.include_site_pages)


class _ConfiguredSitesCheck(_SharepointCheck):
    """The configured site URLs are well formed, on the tenant's host, and
    Graph resolves each of the first few."""

    def __init__(self) -> None:
        super().__init__(
            check_id="sharepoint_configured_sites",
            display_name="Configured sites resolve",
            remediation=(
                "Use full site URLs on this tenant (https://tenant.sharepoint.com/"
                "sites/name or /teams/name, https://tenant-my.sharepoint.com/"
                "personal/name). " + _READ_REMEDIATION
            ),
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return bool(_configured_sites(form_state.config))

    def run(self, context: CapabilityCheckContext) -> None:
        config: SharepointConnectorConfig = _config(context)
        site_urls: list[str] = _configured_sites(config)
        environment: MicrosoftGraphEnvironment = resolve_microsoft_environment(
            config.graph_api_host, config.authority_host
        )
        tenant_domain: str | None = tenant_domain_from_site_urls(site_urls)
        for site_url in site_urls:
            validate_site_url(
                site_url, environment.sharepoint_domain_suffix, tenant_domain
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
                "in /sites/name, /teams/name or /personal/name."
            )
        gateway: SharepointSourceOperations = _gateway(context)
        for site in _descriptors(config)[:_PROBE_SITES]:
            try:
                gateway.get_site_id(site_url=site.url)
            except MicrosoftGraphError as error:
                _raise_for_read_error(
                    error,
                    f"The app cannot read the site {site.url}",
                    f"Graph has no site at {site.url}. Check the URL.",
                )


class _SitesVisibleCheck(_SharepointCheck):
    """Without configured sites the connector indexes every site it can list,
    which needs a tenant-wide read grant: `Sites.Selected` lists nothing."""

    def __init__(self) -> None:
        super().__init__(
            check_id="sharepoint_sites_visible",
            display_name="Tenant sites can be listed",
            remediation=(
                "Grant `Sites.Read.All` (application permission) and admin-consent "
                "it, or configure the site URLs to index."
            ),
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return not _configured_sites(form_state.config)

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            site_urls: list[str] = _gateway(context).list_site_urls(max_pages=1)
        except MicrosoftGraphError as error:
            raise_for_graph_error(
                error,
                "The app cannot list the tenant's sites.",
                remediation=_READ_REMEDIATION,
            )
        if not site_urls:
            raise ConnectorValidationError(
                "Graph lists no sites for this app. With `Sites.Selected` the "
                "listing is empty, so configure the site URLs to index."
            )


class _ConfiguredFolderCheck(_SharepointCheck):
    """A site URL that goes past the library names a folder, which must exist
    in that library. Pages do not read libraries, so this is a documents
    rule."""

    def __init__(self) -> None:
        super().__init__(
            check_id="sharepoint_configured_folder",
            display_name="Configured folders exist",
            remediation=(
                "Use the folder's path inside the library as it appears in the "
                "site URL."
            ),
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return form_state.config.include_site_documents and any(
            site.folder_path for site in _descriptors(form_state.config)
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: SharepointSourceOperations = _gateway(context)
        scoped: list[tuple[SiteDescriptor, str]] = [
            (site, site.folder_path)
            for site in _descriptors(_config(context))
            if site.folder_path
        ]
        for site, folder_path in scoped[:_PROBE_SITES]:
            folder_url: str = f"{site.url}/{site.drive_name}/{folder_path}"
            for drive in _site_drives(context, site):
                try:
                    gateway.resolve_folder(
                        drive_id=drive.drive_id, folder_path=folder_path
                    )
                except MicrosoftGraphError as error:
                    _raise_for_read_error(
                        error,
                        f"The app cannot read the folder {folder_url}",
                        f"No folder at {folder_url}. Check the path.",
                    )


class _DocumentsReadCheck(_SharepointCheck):
    """The first non-empty probe library answers a delta page and lists its
    files, and one file reads by id, with its content when it is small."""

    def __init__(self) -> None:
        super().__init__(
            check_id="sharepoint_documents_read",
            display_name="Site documents are readable",
            remediation=_READ_REMEDIATION,
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return form_state.config.include_site_documents

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: SharepointSourceOperations = _gateway(context)
        config: SharepointConnectorConfig = _config(context)
        graph_api_base: str = _graph_api_base(config)
        probed: int = 0
        excluded_paths: list[str] = _excluded_paths(config)
        for site in _probe_sites(context):
            for drive in _site_drives(context, site):
                if probed == _PROBE_LIBRARIES:
                    raise UnexpectedValidationError(
                        f"The first {_PROBE_LIBRARIES} libraries list no file "
                        "indexing would read, so no file was read."
                    )
                probed += 1
                item: DriveItemData | None = _first_indexable_file(
                    gateway, graph_api_base, site, drive, excluded_paths
                )
                if item is None:
                    continue
                self._read_one(gateway, drive, item)
                return
        if not probed:
            raise UnexpectedValidationError(
                "No library was found on the probe sites, so no file was read."
            )

    def _read_one(
        self, gateway: SharepointSourceOperations, drive: SiteDrive, item: DriveItemData
    ) -> None:
        try:
            found: DriveItemData | None = gateway.get_drive_item(
                drive_id=drive.drive_id, item_id=item.id
            )
            if found is None:
                raise UnexpectedValidationError(
                    f"Graph listed `{item.name}` and then did not answer it by id."
                )
            if item.size is not None and item.size <= _MAX_PROBE_DOWNLOAD_BYTES:
                gateway.read_item_bytes(
                    drive_id=drive.drive_id,
                    item=item,
                    max_bytes=_MAX_PROBE_DOWNLOAD_BYTES,
                )
        except MicrosoftGraphError as error:
            raise_for_graph_error(
                error,
                f"The app cannot read `{item.name}` in {drive.display_name}.",
                remediation=_READ_REMEDIATION,
            )


class _SitePagesReadCheck(_SharepointCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="sharepoint_site_pages_read",
            display_name="Site pages are readable",
            remediation=_READ_REMEDIATION,
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return form_state.config.include_site_pages

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: SharepointSourceOperations = _gateway(context)
        for site in _probe_sites(context):
            try:
                site_id: str = gateway.get_site_id(site_url=site.url)
            except MicrosoftGraphError as error:
                _raise_for_read_error(
                    error,
                    f"The app cannot read the site {site.url}",
                    f"Graph has no site at {site.url}. Check the URL.",
                )
            try:
                listing: SitePagesPage = _list_site_pages(gateway, site_id)
            except MicrosoftGraphError as error:
                # A classic site has no pages listing. Indexing skips it, so
                # the next probe site answers for the grant.
                if error.status == 404:
                    continue
                _raise_for_read_error(
                    error,
                    f"The app cannot list the pages of {site.url}",
                    f"Graph lists no pages for {site.url}.",
                )
            page_id: str | None = next(
                (page["id"] for page in listing.pages if page.get("id")), None
            )
            if page_id is None:
                continue
            try:
                gateway.get_site_page(
                    site_id=site_id, page_id=page_id, expand_canvas=True
                )
            except MicrosoftGraphError as error:
                # Indexing keeps the page's metadata when its canvas is
                # corrupt, so that is not a failure of the grant.
                if is_graph_invalid_request(error):
                    return
                _raise_for_read_error(
                    error,
                    f"The app cannot read a page of {site.url}",
                    f"Graph lists page {page_id} of {site.url} and then has no page.",
                )
            return


class _CertificateAuthCheck(_SharepointCheck):
    """SharePoint REST accepts an app-only token only from a certificate, so
    no grant makes a client-secret credential sync permissions."""

    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id="sharepoint_certificate_auth",
            display_name="Credential can reach SharePoint REST",
            remediation=_CERTIFICATE_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            method: MicrosoftAuthMethod = _gateway(context).get_auth_method()
        except MicrosoftAuthError as error:
            raise_for_auth_error(error)
        if not method.supports_sharepoint_rest:
            raise ConnectorValidationError(
                "Permission sync needs the SharePoint REST API, which only accepts "
                "app-only tokens from certificate authentication. This credential "
                "uses a client secret, so SharePoint denies the request no matter "
                "which permissions are granted."
            )


class _SitePermissionsCheck(_SharepointCheck):
    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id="sharepoint_site_permissions_read",
            display_name="Site permissions are readable",
            remediation=_REST_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: SharepointSourceOperations = _gateway(context)
        for site in _perm_probe_sites(context):
            _site_assignments(gateway, site)


class _SiteGroupMembersCheck(_SharepointCheck):
    """The members of a SharePoint group a probe site names, the REST read
    that expands site groups. A site naming none has nothing to expand."""

    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id="sharepoint_site_group_members_read",
            display_name="Site group members are readable",
            remediation=_REST_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: SharepointSourceOperations = _gateway(context)
        for site in _perm_probe_sites(context):
            group: SharepointPrincipal | None = _first_group(
                _site_assignments(gateway, site),
                SharepointPrincipalType.SHAREPOINT_GROUP,
            )
            if group is None:
                continue
            try:
                gateway.list_site_group_users(
                    site_url=site.url,
                    group_name=group.login_name,
                    max_rows=_PROBE_GROUP_MEMBERS,
                )
            except MicrosoftGraphError as error:
                _raise_for_rest_error(
                    error,
                    f"The app cannot read the members of `{group.title}` on {site.url}",
                    f"SharePoint has no group `{group.title}` on {site.url}.",
                )
            return


class _EntraNestedGroupsCheck(_SharepointCheck):
    """The groups inside an Entra group a probe site names: document sync
    resolves a document's groups through this read, never their users. A
    group Entra no longer has is skipped, as the sync skips it."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="sharepoint_entra_nested_groups_read",
            display_name="Entra group nesting is readable",
            remediation=_GROUPS_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: SharepointSourceOperations = _gateway(context)
        for site in _perm_probe_sites(context):
            group_id: str | None = _entra_group_id(
                gateway, site, _site_assignments(gateway, site)
            )
            if group_id is None:
                continue
            try:
                gateway.list_nested_entra_groups(
                    group_id=group_id, max_rows=_PROBE_NESTED_GROUPS
                )
            except MicrosoftGraphError as error:
                if error.status == 404:
                    continue
                raise_for_graph_error(
                    error,
                    f"The app cannot read the groups inside Entra group {group_id}.",
                    remediation=_GROUPS_REMEDIATION,
                )
            return


class _EntraGroupMembersCheck(_SharepointCheck):
    """One page of the members of an Entra group a probe site names, under
    the grant group sync expands groups with. One page proves the grant
    without walking a large group. When no probe site names an Entra group,
    one listed group stands in, since a later site may name one."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="sharepoint_entra_group_members_read",
            display_name="Entra group members are readable",
            remediation=_GROUPS_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: SharepointSourceOperations = _gateway(context)
        for site in _perm_probe_sites(context):
            group_id: str | None = _entra_group_id(
                gateway, site, _site_assignments(gateway, site)
            )
            if group_id is None:
                continue
            if self._read_member_page(gateway, group_id):
                return
        fallback: EntraGroup | None = _first_listed_group(gateway)
        if fallback is not None:
            self._read_member_page(gateway, fallback.id)

    def _read_member_page(
        self, gateway: SharepointSourceOperations, group_id: str
    ) -> bool:
        """False for a group Entra no longer has, which the sync skips."""
        try:
            gateway.list_entra_group_member_page(group_id=group_id)
        except MicrosoftGraphError as error:
            if error.status == 404:
                return False
            raise_for_graph_error(
                error,
                f"The app cannot read the members of Entra group {group_id}.",
                remediation=_GROUPS_REMEDIATION,
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
        )
    return next(
        (group for group in page.items if group.id and group.display_name), None
    )


class _EntraGroupEnumerationCheck(_SharepointCheck):
    """The tenant-wide group listing and one member page, the reads behind
    exhaustive Entra enumeration."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="sharepoint_entra_group_enumeration",
            display_name="Entra groups can be enumerated",
            remediation=_GROUPS_REMEDIATION,
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return form_state.config.exhaustive_ad_enumeration

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: SharepointSourceOperations = _gateway(context)
        group: EntraGroup | None = _first_listed_group(gateway)
        if group is None:
            return
        try:
            gateway.list_entra_group_member_page(group_id=group.id)
        except MicrosoftGraphError as error:
            raise_for_graph_error(
                error,
                f"The app cannot read the members of Entra group {group.id}.",
                remediation=_GROUPS_REMEDIATION,
            )


class _DocumentPermissionsCheck(_SharepointCheck):
    """Library, folder and file permissions on the first probe library with a
    list id: the reads behind a library's node, a folder's node and a
    document. A library without a list id is skipped, as the sync skips it.
    Libraries whose first page holds no file prove the library read and pass:
    the sync runs this check before every attempt, so a tenant of empty
    libraries must not block indexing."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="sharepoint_document_permissions_read",
            display_name="Document permissions are readable",
            remediation=_REST_REMEDIATION,
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return form_state.config.include_site_documents

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: SharepointSourceOperations = _gateway(context)
        config: SharepointConnectorConfig = _config(context)
        graph_api_base: str = _graph_api_base(config)
        excluded_paths: list[str] = _excluded_paths(config)
        probed: int = 0
        for site in _perm_probe_sites(context):
            for drive in _site_drives(context, site):
                if drive.list_id is None:
                    continue
                if probed == _PROBE_LIBRARIES:
                    logger.info(
                        "The first %s libraries list no file the sync would read; "
                        "the library permission reads stand for the grant.",
                        _PROBE_LIBRARIES,
                    )
                    return
                probed += 1
                self._read_library(gateway, site, drive, drive.list_id)
                item: DriveItemData | None = _first_indexable_file(
                    gateway, graph_api_base, site, drive, excluded_paths
                )
                if item is None:
                    continue
                self._read_folder(gateway, site, drive, item)
                self._read_item(gateway, config, site, drive, drive.list_id, item)
                return
        if not probed:
            # The sync indexes such libraries without permissions, so this is
            # not a reason to block it.
            logger.warning(
                "No library with a list id was found on the probe sites, so no "
                "document permission was read."
            )

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
        server_relative_path: str = build_folder_server_relative_path(
            drive.web_url, relative_path.rsplit("/", 1)[0]
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
        except MicrosoftGraphError as error:
            if error.status == 404:
                return
            _raise_for_rest_error(
                error,
                f"The app cannot read the permissions of folder {server_relative_path}",
                f"SharePoint has no folder at {server_relative_path}.",
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
        if config.treat_sharing_link_as_public:
            try:
                gateway.list_sharing_link_scopes(item=item)
            except MicrosoftGraphError as error:
                raise_for_graph_error(
                    error,
                    f"The app cannot read the sharing links of `{item.name}`.",
                    remediation=_READ_REMEDIATION,
                )
        try:
            item_id: int | None = gateway.get_list_item_id(item=item)
        except MicrosoftGraphError as error:
            if error.status == 404:
                logger.info(
                    "`%s` went away before its permissions were read.", item.name
                )
                return
            raise_for_graph_error(
                error,
                f"The app cannot read the list item id of `{item.name}`.",
                remediation=_READ_REMEDIATION,
            )
        if item_id is None:
            raise UnexpectedValidationError(
                f"Graph lists `{item.name}` without its list item id, so its "
                "permissions cannot be read."
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
            # The sync records a failure for an item that went away between
            # the listing and the read and moves on.
            if error.status == 404:
                logger.info(
                    "`%s` went away before its permissions were read.", item.name
                )
                return
            _raise_for_rest_error(
                error,
                f"The app cannot read the permissions of `{item.name}` in "
                f"{drive.display_name}",
                f"SharePoint has no item `{item.name}` in {drive.display_name}.",
            )


class _PagePermissionsCheck(_SharepointCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="sharepoint_page_permissions_read",
            display_name="Page permissions are readable",
            remediation=_REST_REMEDIATION,
        )

    def applies(self, form_state: FormState[SharepointConnectorConfig]) -> bool:
        return form_state.config.include_site_pages

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: SharepointSourceOperations = _gateway(context)
        for site in _perm_probe_sites(context):
            try:
                site_id: str = gateway.get_site_id(site_url=site.url)
            except MicrosoftGraphError as error:
                _raise_for_read_error(
                    error,
                    f"The app cannot read the site {site.url}",
                    f"Graph has no site at {site.url}. Check the URL.",
                )
            try:
                listing: SitePagesPage = _list_site_pages(gateway, site_id)
            except MicrosoftGraphError as error:
                # A classic site has no pages listing, and the sync skips it.
                if error.status == 404:
                    continue
                _raise_for_read_error(
                    error,
                    f"The app cannot list the pages of {site.url}",
                    f"Graph lists no pages for {site.url}.",
                )
            page_url: str | None = next(
                (page["webUrl"] for page in listing.pages if page.get("webUrl")),
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
                    continue
                _raise_for_rest_error(
                    error,
                    f"The app cannot read the permissions of page {page_url}",
                    f"SharePoint has no page at {page_url}.",
                )
            return


def build_sharepoint_indexing_checks() -> list[CapabilityCheck]:
    return [
        _TokenCheck(),
        _ContentTypesCheck(),
        _ConfiguredSitesCheck(),
        _SitesVisibleCheck(),
        _ConfiguredFolderCheck(),
        _DocumentsReadCheck(),
        _SitePagesReadCheck(),
    ]


def build_sharepoint_doc_permission_sync_checks() -> list[CapabilityCheck]:
    capability: CredentialCapability = CredentialCapability.DOC_PERMISSION_SYNC
    return [
        _CertificateAuthCheck(capability),
        _SitePermissionsCheck(capability),
        _SiteGroupMembersCheck(capability),
        _EntraNestedGroupsCheck(),
        _DocumentPermissionsCheck(),
        _PagePermissionsCheck(),
    ]


def build_sharepoint_group_sync_checks() -> list[CapabilityCheck]:
    capability: CredentialCapability = CredentialCapability.EXTERNAL_GROUP_SYNC
    return [
        _CertificateAuthCheck(capability),
        _SitePermissionsCheck(capability),
        _SiteGroupMembersCheck(capability),
        _EntraGroupMembersCheck(),
        _EntraGroupEnumerationCheck(),
    ]
