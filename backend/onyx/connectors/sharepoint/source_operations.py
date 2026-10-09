"""The SharePoint source-operations gateway: every Graph and SharePoint REST
call the connector and its permission sync make, as plain data.

Sites and drives come from the office365 Graph SDK, site pages and items from
the raw Graph client the drive helpers in ``microsoft_utils`` already use, and
the permission reads from ``sharepoint_rest``. This is the only file under
``connectors/sharepoint`` and its EE permission package that imports the SDKs.
"""

import time
from collections.abc import Generator
from datetime import datetime
from typing import Any

import msal
import requests
from office365.entity_collection import EntityCollection
from office365.graph_client import GraphClient
from office365.onedrive.drives.drive import Drive
from office365.onedrive.lists.list import List as GraphList
from office365.onedrive.sites.site import Site
from office365.onedrive.sites.sites_with_root import SitesWithRoot
from office365.runtime.auth.token_response import TokenResponse
from office365.sharepoint.client_context import ClientContext

from onyx.configs.app_configs import SHAREPOINT_CONNECTOR_SIZE_THRESHOLD
from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.microsoft_utils.config import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
)
from onyx.connectors.microsoft_utils.drive_delta import (
    DriveDeltaFetchResult,
    fetch_drive_delta_checkpoint_page,
)
from onyx.connectors.microsoft_utils.drive_items import (
    DRIVE_ITEM_SELECT_FIELDS,
    DriveFolderReference,
    DriveItemContent,
    DriveItemData,
    extract_drive_item_content,
    iter_drive_items_delta,
    iter_drive_items_paged,
    resolve_drive_folder,
)
from onyx.connectors.microsoft_utils.entra import (
    ENTRA_NAMED_GROUP_SELECT,
    ENTRA_PAGE_SIZE,
    EntraDirectoryObject,
    EntraGroup,
    EntraPage,
    fetch_entra_page,
)
from onyx.connectors.microsoft_utils.graph_auth import (
    MicrosoftAuthContext,
    MicrosoftAuthMethod,
    acquire_token_for_rest,
)
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient
from onyx.connectors.microsoft_utils.graph_env import (
    MicrosoftGraphEnvironment,
    resolve_microsoft_environment,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError,
    raise_microsoft_errors,
)
from onyx.connectors.microsoft_utils.graph_gateway import (
    MicrosoftGraphAuthConfig,
    MicrosoftGraphGateway,
)
from onyx.connectors.microsoft_utils.models import (
    EntraMember,
    SharepointPrincipal,
    SharepointRoleAssignment,
    SharepointSecurable,
)
from onyx.connectors.microsoft_utils.sharepoint_rest import SharepointRestReads
from onyx.connectors.sharepoint.connector_utils import (
    tenant_domain_from_site_urls,
    validate_site_url_host,
)
from onyx.connectors.sharepoint.models import (
    SharepointCredentials,
    SharepointDrive,
    SitePagesPage,
)
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.file_store.staging import RawFileCallback
from onyx.utils.logger import setup_logger

logger = setup_logger()

GRAPH_API_VERSION = "v1.0"
CONFIG_AUTHORITY_HOST = "authority_host"
CONFIG_GRAPH_API_HOST = "graph_api_host"
CONFIG_SITES = "sites"
DRIVE_LIST_PROPERTY = "list"
DRIVE_SELECT_FIELDS = ["id", "name", "webUrl", "driveType"]
DRIVE_EXPAND_FIELDS = [f"{DRIVE_LIST_PROPERTY}($select=id)"]
SITE_PAGE_TYPE = "microsoft.graph.sitePage"
CANVAS_EXPAND_PARAMS = {"$expand": "canvasLayout"}
REST_PROBE_TIMEOUT_S = 10

# The SDK's ClientContext caches its first token and never calls back for a
# new one, so the context is rebuilt well inside the token's 60-75 minute life.
REST_CTX_MAX_AGE_S = 30 * 60

_UNTESTED = "Checks land in the next PR of the stack."


def _drive(drive: Drive) -> SharepointDrive:
    expanded_list: object = drive.properties.get(DRIVE_LIST_PROPERTY)
    if expanded_list is not None and not isinstance(expanded_list, GraphList):
        raise ValueError("Graph drive list relationship has an unexpected type")
    return SharepointDrive(
        id=drive.id,
        name=drive.name,
        web_url=drive.web_url,
        drive_type=drive.drive_type,
        list_id=expanded_list.id if expanded_list is not None else None,
    )


def _iter_site_listing(sites: SitesWithRoot) -> Generator[Site, None, None]:
    while sites:
        if sites.current_page:
            yield from sites.current_page
        if not sites.has_next:
            break
        sites = sites._get_next().execute_query()


class SharepointSourceOperations(SourceOperations):
    source = DocumentSource.SHAREPOINT
    sdk_modules = ("msal", "requests", "office365")
    # The hosts bind the credential to a cloud, and the configured sites name
    # the tenant the REST token is minted for.
    config_keys = frozenset(
        {CONFIG_AUTHORITY_HOST, CONFIG_GRAPH_API_HOST, CONFIG_SITES}
    )

    _environment: MicrosoftGraphEnvironment | None = None
    _graph_gateway: MicrosoftGraphGateway | None = None
    _sdk_client: GraphClient | None = None
    _tenant_domain_cache: str | None = None
    _cached_rest_ctx: ClientContext | None = None
    _cached_rest_ctx_url: str | None = None
    _cached_rest_ctx_created_at: float = 0.0

    def _config(self, key: str, default: str) -> str:
        return str((self.connector_specific_config or {}).get(key) or default).rstrip(
            "/"
        )

    def _sites(self) -> list[str]:
        sites = (self.connector_specific_config or {}).get(CONFIG_SITES) or []
        return [str(site) for site in sites]

    def _env(self) -> MicrosoftGraphEnvironment:
        if self._environment is None:
            self._environment = resolve_microsoft_environment(
                self._config(CONFIG_GRAPH_API_HOST, DEFAULT_GRAPH_API_HOST),
                self._config(CONFIG_AUTHORITY_HOST, DEFAULT_AUTHORITY_HOST),
            )
        return self._environment

    def _credentials(self) -> SharepointCredentials:
        return SharepointCredentials.model_validate(
            self.credentials_provider.get_credentials()
        )

    def _gateway(self) -> MicrosoftGraphGateway:
        if self._graph_gateway is not None:
            return self._graph_gateway
        credential: SharepointCredentials = self._credentials()
        self._graph_gateway = MicrosoftGraphGateway(
            auth_config=MicrosoftGraphAuthConfig(
                client_id=credential.sp_client_id,
                directory_id=credential.sp_directory_id,
                authority_host=self._env().authority_host,
                auth_method=credential.authentication_method,
                client_secret=credential.sp_client_secret,
                private_key_b64=credential.sp_private_key,
                certificate_password=credential.sp_certificate_password,
            ),
            graph_api_host=self._env().graph_host,
            graph_api_version=GRAPH_API_VERSION,
        )
        return self._graph_gateway

    def _auth(self) -> MicrosoftAuthContext:
        return self._gateway().auth_context

    def _base(self) -> str:
        return self._gateway().graph_api_base

    def _graph_api(self) -> GraphApiClient:
        return self._gateway().client

    def _get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        return self._graph_api().get_json(url, params)

    def _graph_client(self) -> GraphClient:
        """The office365 SDK client, for the site, drive and permission reads."""
        if self._sdk_client is None:
            gateway: MicrosoftGraphGateway = self._gateway()
            self._sdk_client = GraphClient(
                gateway.token_response, environment=self._env().environment
            )
        return self._sdk_client

    def _tenant_domain(self) -> str:
        """The tenant label the REST token is minted for: from the configured
        site URLs, else from the root site, which needs no extra grant."""
        if self._tenant_domain_cache is not None:
            return self._tenant_domain_cache
        from_sites: str | None = tenant_domain_from_site_urls(self._sites())
        if from_sites:
            logger.info("Resolved tenant domain '%s' from site URLs", from_sites)
            self._tenant_domain_cache = from_sites
            return from_sites
        logger.info("No site URLs available; resolving tenant domain from root site")
        with raise_microsoft_errors():
            root_site: Site = self._graph_client().sites.root.get().execute_query()
        hostname: str | None = root_site.site_collection.hostname
        if not hostname:
            raise ConnectorValidationError(
                "Could not determine tenant domain from root site"
            )
        tenant_domain: str = hostname.split(".")[0]
        logger.info(
            "Resolved tenant domain '%s' from root site hostname '%s'",
            tenant_domain,
            hostname,
        )
        self._tenant_domain_cache = tenant_domain
        return tenant_domain

    def _rest_context(self, site_url: str) -> ClientContext:
        """A SharePoint REST context for one site, kept until it changes site
        or ages out. A rebuild also rebuilds the MSAL app, so its empty token
        cache guarantees a fresh token from Azure AD."""
        suffix: str = self._env().sharepoint_domain_suffix
        # Re-checked here because group sync and discovered sites reach this
        # without validation.
        validate_site_url_host(site_url, suffix, self._tenant_domain())

        elapsed: float = time.monotonic() - self._cached_rest_ctx_created_at
        if (
            self._cached_rest_ctx is not None
            and self._cached_rest_ctx_url == site_url
            and elapsed <= REST_CTX_MAX_AGE_S
        ):
            return self._cached_rest_ctx

        if self._cached_rest_ctx is not None:
            logger.info(
                "Rebuilding SharePoint REST client context (elapsed=%.0fs, site_changed=%s)",
                elapsed,
                self._cached_rest_ctx_url != site_url,
            )
            self._graph_gateway = None
            self._sdk_client = None

        msal_app: msal.ConfidentialClientApplication = self._auth().app
        tenant_domain: str = self._tenant_domain()
        self._cached_rest_ctx = ClientContext(site_url).with_access_token(
            lambda: acquire_token_for_rest(msal_app, tenant_domain, suffix)
        )
        self._cached_rest_ctx_url = site_url
        self._cached_rest_ctx_created_at = time.monotonic()
        return self._cached_rest_ctx

    def _reads(self) -> SharepointRestReads:
        return SharepointRestReads(
            self._rest_context, self._graph_client(), self._graph_api()
        )

    def _site_pages_url(self, site_id: str) -> str:
        return f"{self._base()}/sites/{site_id}/pages"

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_auth_method(self) -> MicrosoftAuthMethod:
        """Which credential type signed in. SharePoint REST accepts an app-only
        token only from a certificate."""
        return self._auth().method

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def resolve_tenant_domain(self) -> str:
        return self._tenant_domain()

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_site_urls(self) -> list[str]:
        """Every site collection in the tenant, by web URL."""
        with raise_microsoft_errors():
            sites: SitesWithRoot = (
                self._graph_client().sites.get_all_sites().execute_query()
            )
            return [site.web_url for site in _iter_site_listing(sites) if site.web_url]

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_site_id(self, *, site_url: str) -> str:
        with raise_microsoft_errors():
            site: Site = self._graph_client().sites.get_by_url(site_url)
            site.execute_query()
        if not site.id:
            raise RuntimeError(f"Graph answered site {site_url} without an id")
        return site.id

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_drives(self, *, site_url: str) -> list[SharepointDrive]:
        with raise_microsoft_errors():
            site: Site = self._graph_client().sites.get_by_url(site_url)
            drives: EntityCollection[Drive] = (
                site.drives.select(DRIVE_SELECT_FIELDS)
                .expand(DRIVE_EXPAND_FIELDS)
                .get_all(page_loaded=lambda _: None)
                .execute_query()
            )
        return [_drive(drive) for drive in drives]

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_site_pages(
        self, *, site_id: str, next_link: str | None = None, expand_canvas: bool
    ) -> SitePagesPage:
        """One listing page of a site's modern pages. A next link already
        embeds the query, so the canvas expansion applies to the first page."""
        url: str = next_link or f"{self._site_pages_url(site_id)}/{SITE_PAGE_TYPE}"
        params: dict[str, str] | None = (
            CANVAS_EXPAND_PARAMS if expand_canvas and next_link is None else None
        )
        with raise_microsoft_errors():
            data: dict[str, Any] = self._get(url, params)
        return SitePagesPage(
            pages=data.get("value", []), next_link=data.get("@odata.nextLink")
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_site_page(
        self, *, site_id: str, page_id: str, expand_canvas: bool
    ) -> dict[str, Any]:
        url: str = f"{self._site_pages_url(site_id)}/{page_id}/{SITE_PAGE_TYPE}"
        with raise_microsoft_errors():
            return self._get(url, CANVAS_EXPAND_PARAMS if expand_canvas else None)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def resolve_folder(
        self, *, drive_id: str, folder_path: str
    ) -> DriveFolderReference:
        with raise_microsoft_errors():
            return resolve_drive_folder(self._graph_api(), drive_id, folder_path)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def iter_folder_items(
        self,
        *,
        drive_id: str,
        folder_id: str | None,
        start: datetime | None,
        end: datetime | None,
    ) -> Generator[DriveItemData, None, None]:
        """Every file under a folder, the drive root when ``folder_id`` is
        None, one children page at a time."""
        with raise_microsoft_errors():
            yield from iter_drive_items_paged(
                self._graph_api(),
                drive_id=drive_id,
                folder_id=folder_id,
                start=start,
                end=end,
            )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def iter_delta_items(
        self, *, drive_id: str, start: datetime | None, end: datetime | None
    ) -> Generator[DriveItemData, None, None]:
        """Every changed file of a drive through the delta API, uncheckpointed,
        for the slim walks."""
        with raise_microsoft_errors():
            yield from iter_drive_items_delta(
                self._graph_api(), drive_id=drive_id, start=start, end=end
            )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_delta_page(
        self, *, drive_id: str, page_url: str, allow_full_resync: bool
    ) -> DriveDeltaFetchResult:
        with raise_microsoft_errors():
            return fetch_drive_delta_checkpoint_page(
                self._graph_api(),
                page_url=page_url,
                drive_id=drive_id,
                select_fields=DRIVE_ITEM_SELECT_FIELDS,
                allow_full_resync=allow_full_resync,
            )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_drive_item(self, *, drive_id: str, item_id: str) -> DriveItemData | None:
        """None when the item is not in this drive."""
        try:
            with raise_microsoft_errors():
                item: dict[str, Any] = self._get(
                    f"{self._base()}/drives/{drive_id}/items/{item_id}"
                )
        except MicrosoftGraphError as error:
            if error.status == 404:
                return None
            raise
        return DriveItemData.from_graph_json(item)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def download_item(
        self,
        *,
        item: DriveItemData,
        raw_file_callback: RawFileCallback | None = None,
    ) -> DriveItemContent | None:
        return extract_drive_item_content(
            item,
            SHAREPOINT_CONNECTOR_SIZE_THRESHOLD,
            self._base(),
            self._gateway().access_token(),
            raw_file_callback,
        )

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def probe_rest_access(self, *, site_url: str) -> bool:
        """Whether SharePoint REST accepts a role-assignments read on the
        site. A transport failure counts as accepted, so a blip does not fail
        validation: the sync surfaces a real failure."""
        token: TokenResponse = acquire_token_for_rest(
            self._auth().app,
            self._tenant_domain(),
            self._env().sharepoint_domain_suffix,
        )
        probe_url: str = f"{site_url.rstrip('/')}/_api/web/roleassignments?$top=1"
        try:
            response: requests.Response = requests.get(
                probe_url,
                headers={"Authorization": f"Bearer {token.accessToken}"},
                timeout=REST_PROBE_TIMEOUT_S,
            )
        except requests.RequestException as error:
            logger.warning(
                "RoleAssignments permission probe failed for %s (non-blocking): %s",
                site_url,
                error,
            )
            return True
        return response.status_code not in (401, 403)

    @source_operation(
        capabilities={
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_role_assignments(
        self, *, site_url: str, securable: SharepointSecurable
    ) -> list[SharepointRoleAssignment]:
        return self._reads().list_role_assignments(
            site_url=site_url, securable=securable
        )

    @source_operation(
        capabilities={
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_site_group_users(
        self, *, site_url: str, group_name: str
    ) -> list[SharepointPrincipal]:
        return self._reads().list_site_group_users(
            site_url=site_url, group_name=group_name
        )

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_folder_unique_id(self, *, site_url: str, server_relative_path: str) -> str:
        return self._reads().get_folder_unique_id(
            site_url=site_url, server_relative_path=server_relative_path
        )

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_list_item_id(self, *, item: DriveItemData) -> int | None:
        return self._reads().get_list_item_id(item=item)

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_sharing_link_scopes(self, *, item: DriveItemData) -> list[str]:
        return self._reads().list_sharing_link_scopes(item=item)

    @source_operation(
        capabilities={
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def find_entra_group_id(self, *, display_name: str) -> str | None:
        return self._reads().find_entra_group_id(display_name=display_name)

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_entra_group_members(self, *, group_id: str) -> list[EntraMember]:
        return self._reads().list_entra_group_members(group_id=group_id)

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_nested_entra_groups(self, *, group_id: str) -> list[EntraGroup]:
        return self._reads().list_nested_entra_groups(group_id=group_id)

    @source_operation(
        capabilities={
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_entra_groups(
        self, *, next_link: str | None = None, page_size: int = ENTRA_PAGE_SIZE
    ) -> EntraPage[EntraGroup]:
        """Named groups, a page at a time. A page of one is the permission
        probe for group expansion, which reads under the same grant."""
        with raise_microsoft_errors():
            return fetch_entra_page(
                self._graph_api().get_json,
                url=f"{self._base()}/groups",
                item_model=EntraGroup,
                select_fields=ENTRA_NAMED_GROUP_SELECT,
                next_link=next_link,
                page_size=page_size,
            )

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_entra_group_member_page(
        self, *, group_id: str, next_link: str | None = None
    ) -> EntraPage[EntraDirectoryObject]:
        return self._reads().list_entra_group_member_page(
            group_id=group_id, next_link=next_link
        )
